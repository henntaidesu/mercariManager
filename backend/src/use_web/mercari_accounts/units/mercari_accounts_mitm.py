# -*- coding: utf-8 -*-
"""煤炉账号 MITM 抓取端点：seller_id / 4 个 DPoP 字段。"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import Body, HTTPException

from ....db_manage.models.mercari_account import MercariAccountModel
from ....ssl_mitm_proxy.capture_config import (
    clear_session_marker,
    read_capture_file,
    write_session_marker_ms,
)
from ....ssl_mitm_proxy.runner import (
    default_mitm_proxy_url,
    mitm_status,
    start_mitm_proxy,
)
from ....web_drive import get_web_drive_manager
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import automation_headless_enabled
from .mercari_accounts_helpers import (
    _item_api_dict,
    _norm_headers_dict,
    _norm_seller_id,
)
from .mercari_accounts_models import (
    FetchAuthViaMitmBody,
    FetchSellerIdViaMitmBody,
    IN_PROGRESS_CLICK_XPATH_CANDIDATES,
    MERCARI_IN_PROGRESS_URL,
    MERCARI_LISTINGS_URL,
)

log = logging.getLogger(__name__)


def _mitm_patch_console_lines(patch: Dict[str, Any]) -> List[str]:
    """供终端打印：敏感字段只显示长度与前缀。"""
    lines: List[str] = []
    for k in sorted((patch or {}).keys()):
        v = str(patch.get(k) or "")
        if k in ("authorization", "dpop_list", "dpop_info", "dpop_on_sale_list", "dpop_item_get_info"):
            lines.append(f"  • {k}: 长度 {len(v)}，前缀 {v[:24]}…")
        else:
            disp = v.replace("\n", " ")
            if len(disp) > 100:
                disp = disp[:97] + "…"
            lines.append(f"  • {k}: {disp}")
    return lines


def _apply_mitm_patch_to_account(item: MercariAccountModel, patch: Dict[str, Any]) -> None:
    """将 MITM 写入的 value_patch 合并进现有 value，再经 _norm_headers_dict 校验。"""
    cur = MercariAccountModel._parse_value_json(item.value)
    for k, v in (patch or {}).items():
        if v is not None and str(v).strip():
            cur[str(k)] = str(v).strip()
    if cur.get("dpop_list") and not (cur.get("dpop_info") or "").strip():
        cur["dpop_info"] = cur["dpop_list"]
    normalized = _norm_headers_dict(cur)
    item.value = json.dumps(normalized, ensure_ascii=False)


async def _wait_capture(
    *,
    since_ms: int,
    capture_type: str,
    wait_seconds: int,
    seller_id: Optional[str] = None,
    dpop_field: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        # 直接读该 capture_type 专属文件，不受其他类型请求覆盖干扰
        data = read_capture_file(capture_type)
        if data and int(data.get("ts") or 0) >= since_ms:
            if seller_id:
                sid = str(data.get("seller_id") or "").strip()
                if sid and sid != seller_id:
                    await asyncio.sleep(0.9)
                    continue
            if dpop_field:
                df = str(data.get("dpop_field") or "").strip()
                if df != dpop_field:
                    await asyncio.sleep(0.9)
                    continue
            return data
        await asyncio.sleep(0.9)
    return None


async def _wait_capture_with_progress(
    *,
    since_ms: int,
    capture_type: str,
    wait_seconds: int,
    seller_id: Optional[str] = None,
    dpop_field: Optional[str] = None,
    acquired_fields: Optional[List[str]] = None,
    step_name: str = "",
    url_contains: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """等待捕获并每 3 秒打印一次进度（CLI 可见）。"""
    acquired_fields = acquired_fields or []
    deadline = time.monotonic() + wait_seconds
    next_log_at = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_log_at:
            got = "、".join(acquired_fields) if acquired_fields else "无"
            left = max(0, int(deadline - now))
            msg = (
                f"[MITM][进度] 当前步骤: {step_name or capture_type} | "
                f"已获取字段: {got} | 剩余约 {left}s"
            )
            log.info(msg)
            print(msg, flush=True)
            next_log_at = now + 3.0
        # 直接读该 capture_type 专属文件，不受其他类型请求覆盖干扰
        data = read_capture_file(capture_type)
        if data and int(data.get("ts") or 0) >= since_ms:
            if seller_id:
                sid = str(data.get("seller_id") or "").strip()
                if sid and sid != seller_id:
                    await asyncio.sleep(0.9)
                    continue
            if dpop_field:
                df = str(data.get("dpop_field") or "").strip()
                if df != dpop_field:
                    await asyncio.sleep(0.9)
                    continue
            if url_contains:
                u = str(data.get("url") or "")
                if url_contains not in u:
                    await asyncio.sleep(0.9)
                    continue
            return data
        await asyncio.sleep(0.9)
    return None


async def _click_first_match_xpath(mgr: Any, account_key: str, xpaths: List[str], timeout_ms: int = 25000) -> str:
    """按顺序尝试点击多个 XPath，返回成功的 XPath。"""
    last_exc: Optional[Exception] = None
    for xp in xpaths:
        try:
            await mgr.click_xpath(account_key, xp, timeout_ms=timeout_ms)
            return xp
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"所有候选 XPath 点击失败: {last_exc}")


async def fetch_seller_id_via_mitm(
    body: FetchSellerIdViaMitmBody = Body(default_factory=FetchSellerIdViaMitmBody),
):
    """
    启动 MITM，用指定 WebDrive 会话（如 mercari_prepare / mercari_{id}）经代理打开
    jp.mercari.com/mypage/listings，截获
    GET api.mercari.jp/items/get_items?status=on_sale,stop&... 并从查询参数读取 seller_id。

    全流程通过 ``run_mercari_serial_async`` 进入账号队列；队列空闲后由队列层
    自动关闭浏览器（``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC`` 秒延迟）。
    """
    account_key = (body.account_key or "mercari_prepare").strip()

    async def _do_fetch():
        r = start_mitm_proxy()
        if r.get("error"):
            raise HTTPException(status_code=500, detail=r["error"])

        t0 = int(time.time() * 1000)
        mgr = get_web_drive_manager()
        headless = bool(body.headless) or automation_headless_enabled()
        await mgr.open_session(
            account_key,
            headless=headless,
            start_url=MERCARI_LISTINGS_URL,
            proxy_server=default_mitm_proxy_url(),
            interactive=not headless,
            start_minimized=True,
        )

        cap = await _wait_capture_with_progress(
            since_ms=t0,
            capture_type="items_get_items",
            wait_seconds=body.wait_seconds,
            dpop_field="dpop_on_sale_list",
            step_name="在售列表 seller_id",
        )
        if not cap:
            raise HTTPException(
                status_code=408,
                detail=(
                    "超时：未截获 GET /items/get_items（status 含 on_sale/stop）。"
                    "请确认 MITM 已启动、Edge 已登录煤炉且出品一覧可正常加载。"
                ),
            )

        sid = _norm_seller_id(str(cap.get("seller_id") or "").strip())
        if not sid:
            raise HTTPException(status_code=500, detail="截获请求中未解析到有效 seller_id")

        log.info(
            "[MITM] 已解析 seller_id=%s account_key=%s url=%s",
            sid,
            account_key,
            cap.get("url") or "",
        )
        return {
            "success": True,
            "data": {
                "seller_id": sid,
                "url": cap.get("url"),
                "ts": cap.get("ts"),
                "account_key": account_key,
            },
            "mitm": mitm_status(),
        }

    return await run_mercari_serial_async(account_key, _do_fetch)


async def fetch_auth_via_mitm(
    aid: int,
    body: Optional[FetchAuthViaMitmBody] = Body(default=None),
):
    """
    启动 MITM（若未运行），按固定顺序抓取并写回：
    1) DPoP_List: GET /items/get_items?status=trading
    2) DPoP_Info: GET /transaction_evidences/get
    3) DPoP_OnSale-List: GET /items/get_items?status=on_sale|stop
    4) DPoP_ItemGet-Info: GET /items/get

    全流程通过 ``run_mercari_serial_async`` 进入账号队列；队列空闲后由队列层
    自动关闭浏览器（``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC`` 秒延迟）。
    """
    cfg = body or FetchAuthViaMitmBody()

    item = MercariAccountModel.find_by_id(id=aid)
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")
    sid_cfg = _norm_seller_id(item.seller_id)
    if not sid_cfg:
        raise HTTPException(status_code=400, detail="请先填写卖家 ID（须与请求中 seller_id 一致）")

    async def _do_fetch():
        r = start_mitm_proxy()
        if r.get("error"):
            raise HTTPException(status_code=500, detail=r["error"])

        t0 = int(time.time() * 1000)
        write_session_marker_ms(aid, t0)
        try:
            mgr = None
            if cfg.open_browser:
                mgr = get_web_drive_manager()
                from ....web_drive.core.mitm_session import clone_main_profile_cookies
                from ....web_drive.core.paths import mercari_automation_key

                # 使用同步/自动化专用无头 profile（mercari_{id}__sync）：
                # 空白页启动 → 从主 profile 克隆登录 Cookie → 再导航取引中一覧，
                # 不影响 /mercari-accounts「打开浏览器」的有头主 profile。
                auto_key = mercari_automation_key(aid)
                await mgr.close_session(auto_key, force=True)
                headless = automation_headless_enabled()
                await mgr.open_session(
                    auto_key,
                    headless=headless,
                    proxy_server=default_mitm_proxy_url(),
                    interactive=False,
                    start_minimized=True,
                )
                await clone_main_profile_cookies(mgr, aid, auto_key)
                await mgr.reload_active_tab(auto_key, MERCARI_IN_PROGRESS_URL)

            patch: Dict[str, Any] = {}
            capture_meta: Dict[str, Any] = {"seller_id": sid_cfg}
            acquired_fields: List[str] = []

            # Step 1: DPoP_List
            cap_list = await _wait_capture_with_progress(
                since_ms=t0,
                capture_type="items_get_items",
                wait_seconds=cfg.wait_seconds,
                seller_id=sid_cfg,
                dpop_field="dpop_list",
                acquired_fields=acquired_fields,
                step_name="Step 1/4 DPoP_List",
            )
            if not cap_list:
                raise HTTPException(status_code=408, detail="步骤1失败：未截获 DPoP_List（GET /items/get_items?status=trading）")
            print(f"[MITM] 截获 URL(1/4 dpop_list): {cap_list.get('url') or ''}", flush=True)
            patch.update(cap_list.get("value_patch") or {})
            if not str(patch.get("dpop_list") or "").strip():
                raise HTTPException(status_code=500, detail="步骤1失败：截获到请求但缺少 dpop_list")
            acquired_fields.append("dpop_list")
            capture_meta["dpop_list_url"] = cap_list.get("url")
            capture_meta["dpop_list_ts"] = cap_list.get("ts")
            log.info("[MITM] Step 1 完成，等待 3s 后进入 Step 2")
            print("[MITM] Step 1 完成，等待 3s 后进入 Step 2", flush=True)
            await asyncio.sleep(3)

            # Step 2: DPoP_Info
            if cfg.open_browser and mgr is not None:
                try:
                    # 先确保处于「取引中」页，再点击首条交易触发 transaction_evidences/get
                    await mgr.open_new_tab(auto_key, MERCARI_IN_PROGRESS_URL)
                    clicked = await _click_first_match_xpath(
                        mgr,
                        auto_key,
                        [cfg.in_progress_xpath, *list(IN_PROGRESS_CLICK_XPATH_CANDIDATES)],
                        timeout_ms=25000,
                    )
                    log.info("[MITM] Step 2 点击成功 XPath: %s", clicked)
                    print(f"[MITM] Step 2 点击成功 XPath: {clicked}", flush=True)
                except Exception as exc:
                    raise HTTPException(
                        status_code=500,
                        detail=f"步骤2前置失败：自动点击「取引中」首条失败（可能无取引中数据或页面结构变化）: {exc}",
                    ) from exc
            cap_info = await _wait_capture_with_progress(
                since_ms=int(cap_list.get("ts") or t0),
                capture_type="transaction_evidences_get",
                wait_seconds=cfg.wait_seconds,
                dpop_field="dpop_info",
                acquired_fields=acquired_fields,
                step_name="Step 2/4 DPoP_Info",
                url_contains="/transaction_evidences/get?",
            )
            if not cap_info:
                raise HTTPException(status_code=408, detail="步骤2失败：未截获 DPoP_Info（GET /transaction_evidences/get）")
            print(f"[MITM] 截获 URL(2/4 dpop_info): {cap_info.get('url') or ''}", flush=True)
            patch.update(cap_info.get("value_patch") or {})
            if not str(patch.get("dpop_info") or "").strip():
                raise HTTPException(status_code=500, detail="步骤2失败：截获到请求但缺少 dpop_info")
            acquired_fields.append("dpop_info")
            capture_meta["dpop_info_url"] = cap_info.get("url")
            capture_meta["dpop_info_ts"] = cap_info.get("ts")
            log.info("[MITM] Step 2 完成，等待 3s 后进入 Step 3")
            print("[MITM] Step 2 完成，等待 3s 后进入 Step 3", flush=True)
            await asyncio.sleep(3)

            # Step 3: DPoP_OnSale-List
            if cfg.open_browser and mgr is not None:
                await mgr.open_new_tab(auto_key, MERCARI_LISTINGS_URL)
            cap_on_sale = await _wait_capture_with_progress(
                since_ms=int(cap_info.get("ts") or t0),
                capture_type="items_get_items",
                wait_seconds=cfg.wait_seconds,
                seller_id=sid_cfg,
                dpop_field="dpop_on_sale_list",
                acquired_fields=acquired_fields,
                step_name="Step 3/4 DPoP_OnSale-List",
            )
            if not cap_on_sale:
                raise HTTPException(status_code=408, detail="步骤3失败：未截获 DPoP_OnSale-List（GET /items/get_items?status=on_sale|stop）")
            print(f"[MITM] 截获 URL(3/4 dpop_on_sale_list): {cap_on_sale.get('url') or ''}", flush=True)
            patch.update(cap_on_sale.get("value_patch") or {})
            if not str(patch.get("dpop_on_sale_list") or "").strip():
                raise HTTPException(status_code=500, detail="步骤3失败：截获到请求但缺少 dpop_on_sale_list")
            acquired_fields.append("dpop_on_sale_list")
            capture_meta["dpop_on_sale_list_url"] = cap_on_sale.get("url")
            capture_meta["dpop_on_sale_list_ts"] = cap_on_sale.get("ts")
            log.info("[MITM] Step 3 完成，等待 3s 后进入 Step 4")
            print("[MITM] Step 3 完成，等待 3s 后进入 Step 4", flush=True)
            await asyncio.sleep(3)

            # Step 4: DPoP_ItemGet-Info
            if cfg.open_browser and mgr is not None:
                try:
                    await mgr.click_xpath(auto_key, cfg.first_item_xpath, timeout_ms=25000)
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"步骤4前置失败：自动点击「出品中」首条失败: {exc}") from exc
            cap_item_get = await _wait_capture_with_progress(
                since_ms=int(cap_on_sale.get("ts") or t0),
                capture_type="items_get",
                wait_seconds=cfg.wait_seconds,
                dpop_field="dpop_item_get_info",
                acquired_fields=acquired_fields,
                step_name="Step 4/4 DPoP_ItemGet-Info",
            )
            if not cap_item_get:
                raise HTTPException(status_code=408, detail="步骤4失败：未截获 DPoP_ItemGet-Info（GET /items/get）")
            print(f"[MITM] 截获 URL(4/4 dpop_item_get_info): {cap_item_get.get('url') or ''}", flush=True)
            patch.update(cap_item_get.get("value_patch") or {})
            if not str(patch.get("dpop_item_get_info") or "").strip():
                raise HTTPException(status_code=500, detail="步骤4失败：截获到请求但缺少 dpop_item_get_info")
            acquired_fields.append("dpop_item_get_info")
            capture_meta["dpop_item_get_info_url"] = cap_item_get.get("url")
            capture_meta["dpop_item_get_info_ts"] = cap_item_get.get("ts")

            sid_cap = _norm_seller_id(str(cap_on_sale.get("seller_id") or sid_cfg).strip())
            if not sid_cap:
                raise HTTPException(status_code=500, detail="捕获中缺少有效 seller_id")
            item.seller_id = sid_cap

            _apply_mitm_patch_to_account(item, patch)
            if not item.save():
                raise HTTPException(status_code=500, detail="保存失败")

            keys_sorted = sorted(patch.keys())
            log.info(
                "[MITM] 捕获已写入账号 id=%s seller_id=%s ts=%s",
                aid,
                sid_cap,
                cap_item_get.get("ts"),
            )
            log.info("[MITM] 截获 URL(1/4 dpop_list): %s", cap_list.get("url") or "")
            log.info("[MITM] 截获 URL(2/4 dpop_info): %s", cap_info.get("url") or "")
            log.info("[MITM] 截获 URL(3/4 dpop_on_sale_list): %s", cap_on_sale.get("url") or "")
            log.info("[MITM] 截获 URL(4/4 dpop_item_get_info): %s", cap_item_get.get("url") or "")
            log.info(
                "[MITM] 本次合并 value 字段 (%d 项): %s",
                len(keys_sorted),
                ", ".join(keys_sorted),
            )
            for line in _mitm_patch_console_lines(patch):
                log.info("[MITM]%s", line)
            # print 不依赖 logging 配置，保证启动脚本控制台一定能看到
            print("\n========== [MITM] 捕获已写入账号 ==========", flush=True)
            print(f"  截获 URL(1/4 dpop_list): {cap_list.get('url') or ''}", flush=True)
            print(f"  截获 URL(2/4 dpop_info): {cap_info.get('url') or ''}", flush=True)
            print(f"  截获 URL(3/4 dpop_on_sale_list): {cap_on_sale.get('url') or ''}", flush=True)
            print(f"  截获 URL(4/4 dpop_item_get_info): {cap_item_get.get('url') or ''}", flush=True)
            print(f"  account_id={aid} seller_id={sid_cap} ts={cap_item_get.get('ts')}", flush=True)
            print(f"  字段({len(keys_sorted)}): {', '.join(keys_sorted)}", flush=True)
            for line in _mitm_patch_console_lines(patch):
                print(f"[MITM]{line}", flush=True)
            print("==========================================\n", flush=True)

            # 认证抓取流程已完成：浏览器关闭由队列层负责（队列空闲后自动关）。

            return {
                "success": True,
                "data": _item_api_dict(item),
                "captured_field_keys": keys_sorted,
                "capture_meta": {**capture_meta, "seller_id": sid_cap},
                "mitm": mitm_status(),
            }
        finally:
            clear_session_marker(aid)

    return await run_mercari_serial_async(queue_key_for_mercari_account(aid), _do_fetch)
