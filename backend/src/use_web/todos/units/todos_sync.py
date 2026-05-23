# -*- coding: utf-8 -*-
"""待办事项同步入口（HTTP 层）。"""

from typing import Any, Dict

from fastapi import HTTPException

from ....db_manage.models.todo_item import TodoItemModel
from ....use_mercari.get_to_du_list.todolist_sync import (
    _resolve_account_id,
    sync_todos_from_mercari,
)
from ....use_mercari.get_to_du_list.transaction_detail import (
    click_change_shipping_method,
    confirm_shipping_selection,
    fetch_transaction_detail,
    send_transaction_message,
    start_select_shipping_class,
    submit_transaction_review,
)
from ....web_drive.core.account_serial_queue import (
    queue_key_for_meilu_account,
    run_meilu_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import meilu_automation_key
from .todos_models import (
    ConfirmShippingSelectionRequest,
    SendTransactionMessageRequest,
    SubmitTransactionReviewRequest,
    SyncTodosRequest,
)


async def sync_todos(req: SyncTodosRequest) -> Dict[str, Any]:
    """从煤炉同步当前账号的待办事项；按账号串行避免浏览器抢占。"""
    try:
        aid = _resolve_account_id(req.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    stats = await run_meilu_serial_async(
        queue_key_for_meilu_account(aid),
        lambda: sync_todos_from_mercari(account_id=aid),
    )
    return stats


async def fetch_todo_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """处理按钮：打开 transaction 页 → MITM 抓 API → 解析返回；浏览器保持打开。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")

    try:
        data = await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: fetch_transaction_detail(int(todo_id)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
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
    try:
        return await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: send_transaction_message(int(todo_id), req.text),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def start_shipping_class_endpoint(todo_id: int) -> Dict[str, Any]:
    """点 transaction 页的「商品サイズと発送場所を選択する」按钮，等抓 shipping_classes。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: start_select_shipping_class(int(todo_id)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    try:
        return await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: confirm_shipping_selection(int(todo_id), req.class_text, req.facility),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    try:
        return await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: submit_transaction_review(int(todo_id), req.text),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def change_shipping_method_endpoint(todo_id: int) -> Dict[str, Any]:
    """点 transaction 页的「発送方法を変更する」按钮，导航到修改发送方式页（后续由用户在浏览器内完成）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: click_change_shipping_method(int(todo_id)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def close_detail_browser(account_id: int) -> Dict[str, Any]:
    """关闭某账号的 __auto 浏览器（关闭交易详情 dialog 时调用）。"""
    aid = int(account_id)
    if aid <= 0:
        raise HTTPException(status_code=400, detail="account_id 无效")
    mgr = get_web_drive_manager()
    auto_key = meilu_automation_key(aid)
    result = await mgr.close_session_if_automation(auto_key)
    return {"account_id": aid, **(result if isinstance(result, dict) else {})}
