# -*- coding: utf-8 -*-
"""wait-reply: send transaction message"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from .....db_manage.models.todo_item import TodoItemModel
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.mitm_session import mitm_automation_browser
from .....web_drive.core.paths import mercari_automation_key
from ....sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


# 取引消息回复 textarea 的 placeholder 在不同代办类型下不一样：
# - 默认（WaitShipping*）：「なにか分からないことがあれば質問してみましょう。」
# - 待回复（IncomingMessage）：「このたびはご購入ありがとうございます。商品の発送まで今しばらくお待ちください。」
# 任一命中即可，所以用 CSS OR 选择器一次抓两个。
_REPLY_TEXTAREA_PLACEHOLDERS = (
    "なにか分からないことがあれば質問してみましょう。",
    "このたびはご購入ありがとうございます。商品の発送まで今しばらくお待ちください。",
)

_REPLY_SEND_BUTTON_TEXT = "取引メッセージを送る"

async def send_transaction_message(
    todo_id: int,
    text: str,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在主 profile 浏览器内填回复并点击「取引メッセージを送る」。

    若对应账号的浏览器尚未打开（如待回复面板走缓存、未开浏览器），会自动打开交易页再发送；
    已打开（如刚点过「处理/刷新抓取」）则直接复用。待回复（IncomingMessage）发送成功后软删待办并关浏览器。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备发送消息…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id")
    body = (text or "").strip()
    if not body:
        raise ValueError("消息内容不能为空")

    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_automation_key(aid)

    report("attach_browser", "正在连接已打开的浏览器交易页…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception:
        page = None

    if page is None:
        # 浏览器未打开（待回复面板走缓存、未开浏览器）：自动打开交易页。
        # 进入上下文即打开并导航；退出不关闭，浏览器保持打开供下方填表/点发送。
        # 待回复（IncomingMessage）发送成功后由下方收尾逻辑显式关闭。
        report("open_browser", f"正在打开交易页（{item_id}）…")
        url = f"https://jp.mercari.com/transaction/{item_id}"
        try:
            async with mitm_automation_browser(aid, start_url=url):
                pass
            page = await mgr.active_tab_page(auto_key)
        except Exception as exc:
            raise RuntimeError("无法打开交易页，请重试") from exc

    report("locate_textarea", "正在定位回复输入框…")
    # 找到回复 textarea：按多种 placeholder 取 OR 选择器，谁先可见就用谁
    selector = ", ".join(
        f'textarea[placeholder="{p}"]' for p in _REPLY_TEXTAREA_PLACEHOLDERS
    )
    textarea = page.locator(selector)
    try:
        await textarea.first.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到回复输入框（placeholder 不匹配任何已知模板；当前 URL: {page.url}）"
        ) from exc

    report("fill_text", "正在填入回复内容…")
    await textarea.first.fill(body)

    report("click_send", "正在点击「取引メッセージを送る」…")
    # 找到「取引メッセージを送る」按钮（按文本）
    btn = page.get_by_role("button", name=_REPLY_SEND_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        # fallback：直接 :has-text
        btn = page.locator(f'button:has-text("{_REPLY_SEND_BUTTON_TEXT}")')
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_REPLY_SEND_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc

    await btn.first.click()
    log.info(
        "[txdetail] 已点击发送消息 account_id=%s item_id=%s text_len=%s",
        aid,
        item_id,
        len(body),
    )

    # 待回复（IncomingMessage）类型：发送即视为待办完成
    # → 等 1.5s 让 send API 落地 → 软删 todo + 关浏览器（不再次刷新）
    kind = (todo.kind or "").strip()
    completed = False
    if kind == "IncomingMessage":
        report("finalize", "已发送，正在收尾并关闭浏览器…")
        await asyncio.sleep(1.5)
        try:
            todo.is_delete = 1
            todo.synced_at = int(time.time() * 1000)
            todo.save()
            log.info("[reply] IncomingMessage 已软删 todo_id=%s", todo_id)
        except Exception as exc:
            log.warning("[reply] 软删 todo 失败: %s", exc)
        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[reply] IncomingMessage 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[reply] 关浏览器失败: %s", exc)
        completed = True

    report("done", "回复已发送")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "sent": True,
        "completed": completed,
        "text_len": len(body),
    }
