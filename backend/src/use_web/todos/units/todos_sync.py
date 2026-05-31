# -*- coding: utf-8 -*-
"""待办事项同步入口（HTTP 层）。"""

import re
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ....db_manage.models.todo_item import TodoItemModel
from ....use_mercari.get_to_du_list.todolist_sync import (
    _resolve_account_id,
    sync_todos_from_mercari,
)
from ....use_mercari.get_to_du_list.transaction_detail import (
    SUPPORTED_REACTIONS,
    capture_qr_scanner_frame,
    click_change_shipping_method,
    confirm_shipping_selection,
    fetch_transaction_detail,
    finalize_post_shipping,
    read_post_shipping_confirm_info,
    send_message_reaction_by_index,
    send_transaction_message,
    start_select_shipping_class,
    submit_transaction_review,
)
from ....use_mercari.sync_progress import (
    clear_sync_progress,
    get_sync_progress,
)
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_account_key
from .todos_models import (
    ConfirmShippingSelectionRequest,
    SendMessageReactionRequest,
    SendTransactionMessageRequest,
    SubmitTransactionReviewRequest,
    SyncTodosRequest,
    TransactionActionRequest,
)


# 与 listing_post_progress 相同的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


async def sync_todos(req: SyncTodosRequest) -> Dict[str, Any]:
    """从煤炉同步当前账号的待办事项；按账号串行避免浏览器抢占。

    ``progress_job_id`` 与 GET /use_web/todos/sync-progress/{job_id} 配合，
    供前端轮询当前步骤展示全屏等待框。
    """
    jid = (req.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        aid = _resolve_account_id(req.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        stats = await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: sync_todos_from_mercari(
                account_id=aid,
                progress_job_id=jid,
            ),
        )
    finally:
        if jid:
            clear_sync_progress(jid)
    return stats


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
                scan_qr=bool(req.scan_qr), progress_job_id=jid,
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
