# -*- coding: utf-8 -*-
"""待办事项同步入口（HTTP 层）。"""

import logging
import re
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ....db_manage.models.todo_item import TodoItemModel
from ....use_mercari.get_to_du_list.todolist_sync import (
    resolve_enabled_account_ids,
    sync_todos_from_mercari,
)
from ....use_mercari.get_to_du_list.transaction_detail import (
    SUPPORTED_REACTIONS,
    capture_qr_scanner_frame,
    click_change_shipping_method,
    confirm_change_shipping_method,
    confirm_shipping_selection,
    fetch_transaction_detail,
    finalize_post_shipping,
    get_cached_transaction_detail,
    list_uncached_detail_todo_ids,
    revise_shipping_after_qr,
    push_remote_camera_frame,
    read_post_shipping_confirm_info,
    send_message_reaction_by_index,
    send_transaction_message,
    start_select_shipping_class,
    submit_transaction_review,
)
from ....use_mercari.sync_progress import (
    clear_sync_progress,
    get_sync_progress,
    set_sync_progress,
)
from ....use_mercari.sync_lock import (
    LABEL_FULL,
    begin_or_conflict as sync_lock_begin,
    end as sync_lock_end,
)
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_account_key
from .todos_models import (
    CameraFrameRequest,
    ChangeShippingMethodRequest,
    ConfirmShippingSelectionRequest,
    SendMessageReactionRequest,
    SendTransactionMessageRequest,
    SubmitTransactionReviewRequest,
    SyncTodosRequest,
    TransactionActionRequest,
)


log = logging.getLogger(__name__)

# 与 listing_post_progress 相同的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


async def sync_todos(req: SyncTodosRequest) -> Dict[str, Any]:
    """从煤炉同步所有已开启账号（status=active 且 is_open=1）的待办事项；按账号串行避免浏览器抢占。

    不再指定单个账号：点击即同步全部已开启账号，逐个执行并汇总结果。
    ``progress_job_id`` 与 GET /use_web/todos/sync-progress/{job_id} 配合，
    供前端轮询当前步骤展示全屏等待框。
    """
    jid = (req.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        account_ids = resolve_enabled_account_ids()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    lock_token = sync_lock_begin("page", LABEL_FULL)
    accounts: list[Dict[str, Any]] = []
    inserted = updated = marked_deleted = total = 0
    fail_count = 0
    mgr = get_web_drive_manager()
    try:
        # 逐个账号严格串行：每个账号 await 完成（抓取 + 写库）后，必须先关闭其浏览器，
        # 再开始下一个账号。todolist 抓取走单一全局响应文件（请求路径不含 seller_id，
        # 无法区分账号），若两个账号的 /todos 页同时在线会导致响应串台。
        for aid in account_ids:
            try:
                stats = await run_mercari_serial_async(
                    queue_key_for_mercari_account(aid),
                    lambda aid=aid: sync_todos_from_mercari(
                        account_id=aid,
                        progress_job_id=jid,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
                fail_count += 1
                accounts.append({"account_id": aid, "error": str(exc)})
                continue
            else:
                inserted += int(stats.get("inserted", 0) or 0)
                updated += int(stats.get("updated", 0) or 0)
                marked_deleted += int(stats.get("marked_deleted", 0) or 0)
                total += int(stats.get("total", 0) or 0)
                accounts.append(stats)
            finally:
                # 关闭当前账号浏览器，确保与下一账号不重叠（队列层默认 ~10s 后才关，
                # 这里立即强制关闭以消除全局响应文件的串台窗口）。
                try:
                    await mgr.close_session(mercari_account_key(aid), force=True)
                except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                    log.warning(
                        "[todolist] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                    )

        # ── 交易详情预缓存：列表同步完后，为「待发货」「待回复」且尚无交易详情缓存的待办
        #    静默无头补抓一次详情，使前端「处理」面板打开即有缓存可用（无需逐条手动「刷新抓取」）。──
        detail_fetched, detail_failed = await _precache_detail_todos(
            account_ids, jid, mgr
        )
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_sync_progress(jid)

    return {
        "accounts": accounts,
        "account_count": len(account_ids),
        "fail_count": fail_count,
        "inserted": inserted,
        "updated": updated,
        "marked_deleted": marked_deleted,
        "total": total,
        "detail_fetched": detail_fetched,
        "detail_failed": detail_failed,
    }


async def _precache_detail_todos(
    account_ids: list[int], jid: Optional[str], mgr: Any
) -> tuple[int, int]:
    """为各账号下「待发货」「待回复」且无交易详情缓存的待办，按账号串行补抓详情（静默无头）。

    返回 ``(成功条数, 失败条数)``。单条/单账号失败均不抛出，不影响同步整体结果。
    """
    fetched = 0
    failed = 0
    for aid in account_ids:
        todo_ids = list_uncached_detail_todo_ids(aid)
        if not todo_ids:
            continue
        log.info(
            "[todolist] 交易详情预缓存 account_id=%s 共 %d 条", aid, len(todo_ids)
        )
        try:
            for idx, tid in enumerate(todo_ids, start=1):
                if jid:
                    set_sync_progress(
                        jid,
                        "precache_detail",
                        f"补抓交易详情（{idx}/{len(todo_ids)}）…",
                    )
                try:
                    # 同账号多条复用同一浏览器会话（mitm_automation_browser 退出不关闭，
                    # 仅刷新标签页）；串行队列保证不与其它操作抢占同一账号。
                    await run_mercari_serial_async(
                        queue_key_for_mercari_account(aid),
                        lambda tid=tid: fetch_transaction_detail(
                            int(tid), progress_job_id=jid, force_headless=True
                        ),
                        suppress_idle_close=True,
                    )
                    fetched += 1
                except Exception as exc:  # noqa: BLE001 单条失败不阻断其余
                    failed += 1
                    log.warning(
                        "[todolist] 交易详情预缓存失败 todo_id=%s: %s", tid, exc
                    )
        finally:
            # 该账号补抓完毕，强制关闭其浏览器，避免与下一账号或后续操作重叠。
            try:
                await mgr.close_session(mercari_account_key(aid), force=True)
            except Exception as close_exc:  # noqa: BLE001
                log.warning(
                    "[todolist] 预缓存后关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                )
    return fetched, failed


def todos_sync_progress(job_id: str):
    """待办同步执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}


def _validate_job_id(raw: Optional[str]) -> Optional[str]:
    jid = (raw or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")
    return jid


async def get_cached_todo_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """读取交易详情缓存（无浏览器）。点开「处理」面板时优先用本地缓存，避免每次都开浏览器。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    return get_cached_transaction_detail(int(todo_id))


async def fetch_todo_transaction_detail(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """处理按钮：打开 transaction 页 → MITM 抓 API → 解析返回；浏览器保持打开。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")

    jid = _validate_job_id(req.progress_job_id if req else None)

    # 交易详情打开后浏览器需保持打开,等用户在前端继续操作（发送/选择/评价等）;
    # 队列空闲自动关闭由 close_detail_browser 路由或终态 op 显式关闭代替
    try:
        data = await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: fetch_transaction_detail(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)
    return data


async def send_transaction_message_endpoint(
    todo_id: int, req: SendTransactionMessageRequest
) -> Dict[str, Any]:
    """在已开浏览器内填回复 + 点煤炉发送按钮。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: send_transaction_message(int(todo_id), req.text, progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def revise_shipping_after_qr_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """已发行二维码后修改发货方式：点「商品サイズや発送方法を修正する」+ 二次确认「変更する」，清除二维码。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: revise_shipping_after_qr(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def start_shipping_class_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「商品サイズと発送場所を選択する」按钮，等抓 shipping_classes。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: start_select_shipping_class(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def confirm_shipping_selection_endpoint(
    todo_id: int, req: ConfirmShippingSelectionRequest
) -> Dict[str, Any]:
    """提交所选 size + facility：点 size → 次へ → 跳页 → 点 facility → 完了する。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: confirm_shipping_selection(
                int(todo_id), req.class_text, req.facility,
                scan_qr=bool(req.scan_qr),
                generate_code=bool(req.generate_code),
                progress_job_id=jid,
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def submit_transaction_review_endpoint(
    todo_id: int, req: SubmitTransactionReviewRequest
) -> Dict[str, Any]:
    """在已打开浏览器（取引評価页）填评价文本并点击提交按钮。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: submit_transaction_review(int(todo_id), req.text, progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def change_shipping_method_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「発送方法を変更する」按钮，导航到修改发送方式页（后续由用户在浏览器内完成）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: click_change_shipping_method(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def confirm_change_shipping_method_endpoint(
    todo_id: int, req: ChangeShippingMethodRequest
) -> Dict[str, Any]:
    """在 /shipping_method 页选中配送方式并点「変更する」，完成后回到交易页。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: confirm_change_shipping_method(
                int(todo_id),
                req.method_value or "",
                method_label=req.method_label or "",
                progress_job_id=jid,
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def send_message_reaction_endpoint(
    todo_id: int, req: SendMessageReactionRequest
) -> Dict[str, Any]:
    """对买家某条消息发送 emoji 反应（前端用 reaction_index 定位）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    if (req.reaction or "").strip().lower() not in SUPPORTED_REACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"reaction 非法（仅支持 {list(SUPPORTED_REACTIONS)}）",
        )
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: send_message_reaction_by_index(
                int(todo_id),
                req.reaction_index,
                req.reaction,
                message_id=req.message_id,
                progress_job_id=jid,
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def close_detail_browser(account_id: int) -> Dict[str, Any]:
    """关闭某账号的主 profile 浏览器（关闭交易详情 dialog 时调用）。"""
    aid = int(account_id)
    if aid <= 0:
        raise HTTPException(status_code=400, detail="account_id 无效")
    mgr = get_web_drive_manager()
    main_key = mercari_account_key(aid)
    result = await mgr.close_session(main_key, force=True)
    return {"account_id": aid, **(result if isinstance(result, dict) else {})}


async def post_shipping_info_endpoint(todo_id: int) -> Dict[str, Any]:
    """QR 读取成功后，从交易页读取「発送確認符号 / 追跡番号」供前端二次确认展示。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: read_post_shipping_confirm_info(int(todo_id)),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def finalize_post_shipping_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """用户二次确认后：勾选发送用シール → 发送通知 → 「発送しました」。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: finalize_post_shipping(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def qr_scanner_frame_endpoint(todo_id: int) -> Dict[str, Any]:
    """QR スキャナを開いている有頭ブラウザの現在タブを 1 枚スクショして返す（ミラー用）。

    前端が短間隔でポーリングして擬似ライブ映像として描画する。``done=True`` で
    読み取り成功（交易ページへ戻った）と判断し、ポーリングを止める。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: capture_qr_scanner_frame(int(todo_id)),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def camera_frame_endpoint(todo_id: int, req: CameraFrameRequest) -> Dict[str, Any]:
    """客户端摄像头帧 → 推到有头浏览器的虚拟摄像头（QR スキャナ用）。

    前端以 ~15fps 调用：上传一帧 + 取回扫描状态。``done=True`` 表示读取成功
    （已回到 /transaction/），前端据此停止推流并进入发货二次确认。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: push_remote_camera_frame(
                int(todo_id),
                frame=req.frame or "",
                width=int(req.width or 0),
                height=int(req.height or 0),
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
