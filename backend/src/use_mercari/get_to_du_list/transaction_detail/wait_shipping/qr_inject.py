# -*- coding: utf-8 -*-
"""wait-shipping: 把**已解出的二维码文本**送进煤炉扫描页，照片不再进煤炉。

原来的做法是把用户拍的那张照片当作摄像头画面反复推给 ``/qr_code_scanner``，等煤炉自己
读出来——照片糊一点、有反光或阴影就读不出，任务白等十秒后失败，用户得重拍。可后端在
**入队前**就已经用 zxing 把码解出来了（见 ``qr_photo.decode_qr``），那张照片对煤炉毫无
信息增量，只是把我们已知的答案又用一种更差的编码重讲一遍。

改成两层，输入都只有「解出来的那段文本」：

1. ``BarcodeDetector``：Windows 版 Chromium 本来没有这个 API，页面若做特性检测就会落到
   自己的 JS 解码器上；这里在**页面脚本之前**把它装上，``detect()`` 直接返回注入的文本。
   走通的话一个像素都不用解，进扫描页即刻完成。
2. 兜底：把那段文本**重新编码**成一张标准二维码图推进虚拟摄像头。送进去的仍然不是照片，
   而是无反光、无失焦、对比度拉满的合成码，扫描器一帧就能读出。

第 1 层是否被采用取决于煤炉自己的实现，从外部无法断言，所以每次都把命中情况
（``detect()`` 被调用了几次、最终是哪一层完成的）记进任务结果的 ``via``/``detect_calls``
与日志——只有确认第 1 层稳定命中，才谈得上砍掉第 2 层。
``MERCARI_QR_INJECT_RESULT=0`` 可整层关掉直接走第 2 层，用于第 1 层反而把页面弄坏时止血。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

from ....sync.sync_progress import set_sync_progress

log = logging.getLogger(__name__)

#: 关掉第 1 层（结果注入），只用重编码的合成码。见模块文档。
_INJECT_RESULT_ENABLED = os.getenv("MERCARI_QR_INJECT_RESULT", "1").strip() != "0"

#: 注入后等页面自己离开扫描页的时长（秒）。命中就是毫秒级的事，等久了只是推迟兜底。
_INJECT_WAIT_SEC = 3.0

#: 兜底至少要有的时间——``timeout_sec`` 被上面这段吃掉后不能只剩零点几秒。
_FALLBACK_MIN_SEC = 5.0


# ─── 结果注入（第 1 层） ────────────────────────────────────────────
# 必须在页面脚本之前装好：扫描组件挂载时就做特性检测，装晚了它已经选定自己的解码器。
# 因此与 _FAKE_CAMERA_JS 一样，通过 add_init_script（硬导航）+ evaluate（SPA 软导航）
# 两处注入，见 qr_scan._click_scan_qr_and_open_scanner。
QR_RESULT_INJECT_JS = r"""
(() => {
  try {
    if (window.__qrResultInstalled) return true;
    window.__qrResultInstalled = true;
    window.__qrInjectText = '';
    // 煤炉调了几次 detect()：0 说明它根本不走 BarcodeDetector，这一层对它无效
    window.__qrInjectDetectCalls = 0;

    var SIDE = 240;
    function detected(text) {
      return {
        rawValue: text,
        format: 'qr_code',
        boundingBox: {
          x: 0, y: 0, width: SIDE, height: SIDE,
          top: 0, left: 0, right: SIDE, bottom: SIDE
        },
        cornerPoints: [
          { x: 0, y: 0 }, { x: SIDE, y: 0 },
          { x: SIDE, y: SIDE }, { x: 0, y: SIDE }
        ]
      };
    }

    function InjectedBarcodeDetector(options) {
      this.formats = (options && options.formats) || ['qr_code'];
    }
    InjectedBarcodeDetector.getSupportedFormats = function () {
      return Promise.resolve(['qr_code']);
    };
    InjectedBarcodeDetector.prototype.detect = function () {
      window.__qrInjectDetectCalls = (window.__qrInjectDetectCalls || 0) + 1;
      var t = window.__qrInjectText;
      // 还没注入结果时返回空数组（＝这一帧没扫到），不能抛错：页面多半会把异常当作
      // 摄像头故障并直接结束扫描，那样连兜底都没得跑了。
      return Promise.resolve(t ? [detected(t)] : []);
    };
    window.BarcodeDetector = InjectedBarcodeDetector;

    window.__setQrInjectResult = function (text) {
      window.__qrInjectText = String(text || '');
      return true;
    };
    return true;
  } catch (e) { return false; }
})();
"""


async def _scanner_page(todo_id: int):
    """取该待办账号当前的自动化标签页（扫描页应当已经打开）。"""
    from .....db_manage.models.todos.todo_item import TodoItemModel
    from .....web_drive.core.manager import get_web_drive_manager
    from .....web_drive.core.paths import mercari_todo_key

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    mgr = get_web_drive_manager()
    try:
        return await mgr.active_tab_page(mercari_todo_key(int(todo.account_id)))
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc


async def _push_result(todo_id: int, qr_text: str) -> bool:
    """把结果写进页面。装载失败（旧文档没跑到 init script）时就地补装一次。"""
    page = await _scanner_page(todo_id)
    try:
        ok = await page.evaluate(
            "(t) => (typeof window.__setQrInjectResult === 'function')"
            " ? window.__setQrInjectResult(t) : false",
            qr_text,
        )
        if not ok:
            await page.evaluate(QR_RESULT_INJECT_JS)
            ok = await page.evaluate(
                "(t) => (typeof window.__setQrInjectResult === 'function')"
                " ? window.__setQrInjectResult(t) : false",
                qr_text,
            )
        return bool(ok)
    except Exception as exc:
        log.debug("[qrinject] 写入扫码结果失败: %s", exc)
        return False


async def _detect_calls(todo_id: int) -> int:
    """煤炉调了几次我们装的 ``detect()``——用来判断第 1 层对它是否适用。"""
    try:
        page = await _scanner_page(todo_id)
        return int(await page.evaluate("() => window.__qrInjectDetectCalls || 0") or 0)
    except Exception:
        return 0


async def deliver_qr_result_until_scanned(
    todo_id: int,
    qr_text: str,
    *,
    timeout_sec: float,
    interval_sec: float = 0.4,
    progress_job_id: str = "",
) -> Dict[str, Any]:
    """把扫码结果交给煤炉扫描页，直到它认下来（或超时）。照片全程不参与。

    读取成功的判定沿用既有口径：页面离开 ``/qr_code_scanner`` 回到 ``/transaction/``。

    :returns: ``{done, via, detect_calls, elapsed_sec, pushes, url}``；
        ``via`` 是最终生效的那一层（``barcode_detector`` / ``reencoded_qr`` / ``none``）。
    """
    from .....use_web.todos.units.todos_sync.qr_photo import encode_qr_data_url
    from .qr_scan import feed_photo_until_scanned, push_remote_camera_frame

    def report(step: str, label: str) -> None:
        if progress_job_id:
            try:
                set_sync_progress(progress_job_id, step, label)
            except Exception:
                pass

    text = (qr_text or "").strip()
    if not text:
        raise ValueError("没有可注入的扫码结果")

    loop = asyncio.get_running_loop()
    started = loop.time()
    url = ""

    if _INJECT_RESULT_ENABLED:
        report("qr_inject", "正在把扫码结果注入煤炉扫描页…")
        injected = await _push_result(int(todo_id), text)
        log.info("[qrinject] todo=%s 结果注入 %s", todo_id, "成功" if injected else "未装载")
        while loop.time() - started < _INJECT_WAIT_SEC:
            res = await push_remote_camera_frame(int(todo_id))  # frame 为空 → 只读状态
            url = str(res.get("url") or "")
            if res.get("done"):
                calls = await _detect_calls(int(todo_id))
                elapsed = round(loop.time() - started, 1)
                log.info(
                    "[qrinject] todo=%s 煤炉已认下注入的结果（耗时 %.1fs，detect %d 次）",
                    todo_id, elapsed, calls,
                )
                report("qr_scanned", "二维码已读取，正在获取发货信息…")
                return {
                    "done": True, "via": "barcode_detector", "detect_calls": calls,
                    "elapsed_sec": elapsed, "pushes": 0, "url": url,
                }
            if not res.get("on_scanner"):
                # 既不在扫描页也没回交易页：页面被关或跳走了，兜底也没有目标可推
                log.warning("[qrinject] todo=%s 已离开扫描页且未完成（URL=%s）", todo_id, url)
                return {
                    "done": False, "via": "none", "detect_calls": await _detect_calls(int(todo_id)),
                    "elapsed_sec": round(loop.time() - started, 1), "pushes": 0, "url": url,
                }
            await asyncio.sleep(interval_sec)

    detect_calls = await _detect_calls(int(todo_id)) if _INJECT_RESULT_ENABLED else 0
    log.info(
        "[qrinject] todo=%s 结果注入未生效（detect %d 次），改推重编码的二维码",
        todo_id, detect_calls,
    )
    report("qr_reencode", "正在把扫码结果重新编码后送入扫描器…")

    # 兜底：同一段文本重画成标准码。仍然不是用户那张照片。
    remaining = max(float(timeout_sec) - (loop.time() - started), _FALLBACK_MIN_SEC)
    scan = await feed_photo_until_scanned(
        int(todo_id),
        encode_qr_data_url(text),
        timeout_sec=remaining,
        interval_sec=interval_sec,
        progress_job_id=progress_job_id,
    )
    scan["via"] = "reencoded_qr" if scan.get("done") else "none"
    scan["detect_calls"] = detect_calls
    scan["elapsed_sec"] = round(loop.time() - started, 1)
    return scan
