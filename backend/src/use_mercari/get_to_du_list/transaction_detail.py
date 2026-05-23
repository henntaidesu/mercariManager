# -*- coding: utf-8 -*-
"""
待办事项 →「处理」按钮：打开 https://jp.mercari.com/transaction/<item_id>，
通过 **MITM 抓两个关键 API** 还原交易详情字段（不再做 DOM 爬取）：

- GET ``api.mercari.jp/shipping/get_info?transaction_evidence_id=...``
  → 商品名、发送方法、发送元、shipment 状态
- GET ``api.mercari.jp/transaction_messages/get_messages?item_id=...``
  → 买家·卖家消息流（含用户名、时间）

浏览器在抓取后 **保持打开**，方便用户在原生页面上手动操作；下一次「处理」
按钮调用会先关掉旧的 ``__auto`` 会话再开新的（``ensure_session_for_mitm`` 自带）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...db_manage.models.todo_item import TodoItemModel
from ...ssl_mitm_proxy.capture_config import (
    clear_shipping_info_response_file,
    clear_transaction_messages_response_file,
    read_shipping_info_response,
    read_transaction_messages_response,
)
from ...ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy
from ...web_drive.core.manager import EdgeWebDriveManager, get_web_drive_manager
from ...web_drive.core.paths import (
    meilu_automation_key,
    seed_automation_profile_from_account,
)
from ..get_order.get_in_progress_order.get_order_info import apply_item_info_to_order

log = logging.getLogger(__name__)


# 等待两个 API 都被 MITM 截获的总超时（页面加载 + JS 渲染 + API 往返）
_WAIT_TIMEOUT_SEC = 30
# 期间每隔多少秒重新 navigate 一次（兜底：偶发未触发 API）
_RELOAD_INTERVAL_SEC = 20.0


async def _wait_for_both_captures(
    *,
    mgr: EdgeWebDriveManager,
    auto_key: str,
    start_url: str,
    since_ms: int,
    timeout: int = _WAIT_TIMEOUT_SEC,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """同一轮询循环里等两个文件，避免互相干扰的 reload。"""
    deadline = time.monotonic() + timeout
    next_reload = time.monotonic() + _RELOAD_INTERVAL_SEC
    shipping: Optional[Dict[str, Any]] = None
    messages: Optional[Dict[str, Any]] = None
    while time.monotonic() < deadline:
        if shipping is None:
            d = read_shipping_info_response()
            if d and int(d.get("ts") or 0) >= since_ms:
                shipping = d
        if messages is None:
            d = read_transaction_messages_response()
            if d and int(d.get("ts") or 0) >= since_ms:
                messages = d
        if shipping is not None and messages is not None:
            return shipping, messages
        if time.monotonic() >= next_reload:
            next_reload += _RELOAD_INTERVAL_SEC
            try:
                await mgr.reload_active_tab(auto_key, start_url)
            except Exception as exc:
                log.debug("[txdetail] reload 失败（忽略）：%s", exc)
        await asyncio.sleep(0.35)
    return shipping, messages


def _compose_sender_address(origin: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(origin, dict):
        return None
    parts: List[str] = []
    postcode = str(origin.get("postcode") or "").strip()
    if len(postcode) == 7:
        parts.append(f"〒{postcode[:3]}-{postcode[3:]}")
    elif postcode:
        parts.append(f"〒{postcode}")
    region_line = "".join(
        [
            str(origin.get("prefecture") or "").strip(),
            str(origin.get("city") or "").strip(),
        ]
    )
    if region_line:
        parts.append(region_line)
    a1 = str(origin.get("address1") or "").strip()
    a2 = str(origin.get("address2") or "").strip()
    if a1:
        parts.append(a1)
    if a2:
        parts.append(a2)
    family = str(origin.get("family_name") or "").strip()
    first = str(origin.get("first_name") or "").strip()
    name = " ".join([s for s in (family, first) if s])
    if name:
        parts.append(f"{name} 様")
    tel = str(origin.get("telephone") or "").strip()
    if tel:
        parts.append(tel)
    return "\n".join(parts) if parts else None


def _parse_shipping_info(payload: Optional[Dict[str, Any]], local_sender_id: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "product_name": None,
        "shipping_method_name": None,
        "current_shipping_status": None,
        "sender_address": None,
        "shipment_status": None,
        "has_size_location_btn": False,
        "has_change_method_btn": False,
    }
    if not isinstance(payload, dict):
        return out
    body = payload.get("body") or {}
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return out

    # 商品名：优先 data.item.name，回退 data.name（部分接口直接挂在 data 上）
    item = data.get("item") or {}
    if isinstance(item, dict) and item.get("name"):
        out["product_name"] = str(item.get("name")).strip() or None
    elif data.get("name"):
        out["product_name"] = str(data.get("name")).strip() or None

    method = (data.get("shipping_method_name") or "").strip()
    if method:
        out["shipping_method_name"] = method
        out["current_shipping_status"] = f"{method}で発送する"

    shipment = data.get("shipment") or {}
    if isinstance(shipment, dict):
        st = (str(shipment.get("status") or "")).strip().lower()
        if st:
            out["shipment_status"] = st
        # 仅当待发货（fillin / shipping）时才可点这两个按钮
        out["has_change_method_btn"] = st in ("fillin", "shipping")
        out["has_size_location_btn"] = (
            st in ("fillin", "shipping") and bool(shipment.get("is_origin_updatable"))
        )
        out["sender_address"] = _compose_sender_address(shipment.get("origin"))

    return out


def _parse_messages(
    payload: Optional[Dict[str, Any]],
    local_sender_id: Optional[str],
) -> Dict[str, Any]:
    """返回 {messages, buyer_name}"""
    out: Dict[str, Any] = {"messages": [], "buyer_name": None}
    if not isinstance(payload, dict):
        return out
    body = payload.get("body") or {}
    data = body.get("data") or []
    if not isinstance(data, list):
        return out

    buyer_uid: Optional[str] = None
    if local_sender_id:
        buyer_uid = str(local_sender_id).strip() or None

    # 按 created 升序
    items = sorted(
        [m for m in data if isinstance(m, dict)],
        key=lambda m: int(m.get("created") or 0),
    )
    for m in items:
        user = m.get("user") or {}
        uid_raw = m.get("user_id") if m.get("user_id") is not None else user.get("id")
        uid = str(uid_raw).strip() if uid_raw is not None else ""
        is_buyer = bool(buyer_uid) and uid == buyer_uid
        body_text = (m.get("body") or "").strip()
        if not body_text and not user.get("name"):
            continue
        out["messages"].append(
            {
                "from": (user.get("name") or "").strip() or None,
                "text": body_text,
                "at": _format_ts(m.get("created")),
                "is_buyer": is_buyer,
                "user_id": uid or None,
            }
        )
        if is_buyer and not out["buyer_name"]:
            out["buyer_name"] = (user.get("name") or "").strip() or None

    # 兜底：若没拿到买家名，取第一条非空 user.name
    if not out["buyer_name"]:
        for m in out["messages"]:
            if m.get("from"):
                out["buyer_name"] = m["from"]
                break
    return out


def _format_ts(unix_seconds: Any) -> Optional[str]:
    try:
        n = int(unix_seconds)
        if n <= 0:
            return None
        dt = datetime.fromtimestamp(n, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return None


async def fetch_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """打开有头浏览器到 transaction 页 → MITM 等两个 API → 解析返回。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")

    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")

    aid = int(todo.account_id)
    local_sender_id = (todo.sender_id or "").strip() or None
    url = f"https://jp.mercari.com/transaction/{item_id}"
    log.info("[txdetail] 打开交易页 account_id=%s url=%s", aid, url)

    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    try:
        seed_automation_profile_from_account(aid)
    except Exception as exc:
        log.warning("[txdetail] seed __auto profile 失败（继续，使用磁盘旧 Cookie）：%s", exc)

    mgr = get_web_drive_manager()
    auto_key = meilu_automation_key(aid)
    proxy = default_mitm_proxy_url()

    # ── Step 1: 先开 mercari 首页等 5s 刷新 cookie / refresh token ──
    home_url = "https://jp.mercari.com/"
    log.info("[txdetail] 先打开首页 %s 刷新 cookie", home_url)
    await mgr.ensure_session_for_mitm(
        auto_key,
        start_url=home_url,
        proxy_server=proxy,
        headless=False,
        start_minimized=False,
        block_images=False,
    )
    await asyncio.sleep(5.0)

    # ── Step 2: 清空 latest 文件 + 取 since_ms（首页阶段的无关请求不会污染） ──
    clear_shipping_info_response_file()
    clear_transaction_messages_response_file()
    since_ms = int(time.time() * 1000)

    # ── Step 3: 跳转到交易页 ──
    log.info("[txdetail] 跳转到交易页 %s", url)
    try:
        await mgr.reload_active_tab(auto_key, url)
    except Exception as exc:
        log.warning("[txdetail] reload_active_tab 失败（忽略）：%s", exc)

    shipping, messages = await _wait_for_both_captures(
        mgr=mgr,
        auto_key=auto_key,
        start_url=url,
        since_ms=since_ms,
    )

    if shipping is None and messages is None:
        log.warning("[txdetail] 两个 API 均未截获 todo_id=%s", todo_id)
    elif shipping is None:
        log.warning("[txdetail] shipping/get_info 未截获 todo_id=%s", todo_id)
    elif messages is None:
        log.warning("[txdetail] transaction_messages/get_messages 未截获 todo_id=%s", todo_id)

    shipping_part = _parse_shipping_info(shipping, local_sender_id)
    messages_part = _parse_messages(messages, local_sender_id)

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "url": url,
        "captured": {
            "shipping_info": shipping is not None,
            "transaction_messages": messages is not None,
        },
        **shipping_part,
        **messages_part,
    }


# 取引消息回复 textarea 的 placeholder 在不同代办类型下不一样：
# - 默认（WaitShipping*）：「なにか分からないことがあれば質問してみましょう。」
# - 待回复（IncomingMessage）：「このたびはご購入ありがとうございます。商品の発送まで今しばらくお待ちください。」
# 任一命中即可，所以用 CSS OR 选择器一次抓两个。
_REPLY_TEXTAREA_PLACEHOLDERS = (
    "なにか分からないことがあれば質問してみましょう。",
    "このたびはご購入ありがとうございます。商品の発送まで今しばらくお待ちください。",
)
_REPLY_SEND_BUTTON_TEXT = "取引メッセージを送る"

_REVIEW_TEXTAREA_PLACEHOLDER = "例) このたびはお取引ありがとうございました。"
_REVIEW_SUBMIT_BUTTON_TEXT = "購入者を評価して取引完了する"
_REVIEW_CONFIRM_BUTTON_TEXT = "取引を完了する"
_REVIEW_COMPLETED_TEXT = "取引が完了しました"


async def send_transaction_message(todo_id: int, text: str) -> Dict[str, Any]:
    """在已开的 __auto 浏览器内填回复并点击「取引メッセージを送る」。

    要求 ``fetch_transaction_detail`` 已先打开过对应账号的交易页（否则会话不存在/不在目标 URL）。
    """
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
    auto_key = meilu_automation_key(aid)

    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「处理」打开交易页") from exc

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

    await textarea.first.fill(body)

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
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "sent": True,
        "text_len": len(body),
    }


# ====================================================================
# 选择商品尺寸与发送地
# ====================================================================

_SIZE_SELECT_BUTTON_TEXT = "商品サイズと発送場所を選択する"
_CHANGE_METHOD_BUTTON_TEXT = "発送方法を変更する"
_SELECT_NEXT_BUTTON_TEXT = "選択して次へ"
_SELECT_FINISH_BUTTON_TEXT = "選択して完了する"


async def start_select_shipping_class(todo_id: int) -> Dict[str, Any]:
    """点 transaction 页的「商品サイズと発送場所を選択する」按钮 → 等浏览器跳到 /shipping_class。

    尺寸列表由前端硬编码（按 shipping_method_name 区分），不再依赖 MITM 抓取。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)

    mgr = get_web_drive_manager()
    auto_key = meilu_automation_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「处理」打开交易页") from exc

    btn = page.get_by_role("button", name=_SIZE_SELECT_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        btn = page.locator(f'button:has-text("{_SIZE_SELECT_BUTTON_TEXT}")')
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_SIZE_SELECT_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc
    await btn.first.click()
    log.info("[shipping] 已点击「%s」 account_id=%s", _SIZE_SELECT_BUTTON_TEXT, aid)

    # 等浏览器跳到 /shipping_class（用户后续在我们 dialog 内选 size）
    try:
        await page.wait_for_url("**/shipping_class*", timeout=8000)
    except Exception:
        log.warning("[shipping] 未观察到 /shipping_class 导航（可能已经在该页）")

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "clicked": True,
    }


_FACILITY_XPATHS = {
    "post_office": '//*[@id="main"]/div/form/div[1]/div/div[1]/div/div[1]',
    "lawson": '//*[@id="main"]/div/form/div[1]/div/div[1]/div/div[2]',
}


async def confirm_shipping_selection(
    todo_id: int,
    class_text: str,
    facility: Optional[str] = None,
) -> Dict[str, Any]:
    """在 /shipping_class 页选 size → 次へ → 在 /shipping_facilities 页按需点 facility → 完了する。

    ``facility``：
      - ``None``：不点 facility（用于 POST_BOX 唯一选项的 size，页面会自动选好）
      - ``"post_office"`` / ``"lawson"``：按对应 XPath 点击卡片
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    class_text = (class_text or "").strip()
    if not class_text:
        raise ValueError("class_text 不能为空")
    facility = (facility or "").strip().lower() or None
    if facility is not None and facility not in _FACILITY_XPATHS:
        raise ValueError(f"facility 取值非法：{facility}")

    mgr = get_web_drive_manager()
    auto_key = meilu_automation_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    # ── Step 1: 按精确文本匹配点击 size ──
    size_loc = page.get_by_text(class_text, exact=True).first
    try:
        await size_loc.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到尺寸选项「{class_text}」（当前 URL: {page.url}）"
        ) from exc
    await size_loc.click()
    log.info("[shipping] 已选择尺寸「%s」 account_id=%s", class_text, aid)
    await asyncio.sleep(0.2)

    # ── Step 2: 点「選択して次へ」──
    next_btn = page.get_by_role("button", name=_SELECT_NEXT_BUTTON_TEXT)
    try:
        await next_btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        next_btn = page.locator(f'button:has-text("{_SELECT_NEXT_BUTTON_TEXT}")')
        await next_btn.first.wait_for(state="visible", timeout=4000)
    await next_btn.first.click()
    log.info("[shipping] 已点击「%s」 account_id=%s", _SELECT_NEXT_BUTTON_TEXT, aid)

    # ── Step 3: 等浏览器跳到 /shipping_facilities ──
    try:
        await page.wait_for_url("**/shipping_facilities*", timeout=10000)
    except Exception:
        log.warning("[shipping] 未观察到 /shipping_facilities 导航 (当前 URL: %s)", page.url)

    # ── Step 4: 按需点 facility 卡片 ──
    if facility is not None:
        xpath_expr = _FACILITY_XPATHS[facility]
        fac_loc = page.locator(f"xpath={xpath_expr}")
        try:
            await fac_loc.first.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到发货地卡片（facility={facility}，XPath={xpath_expr}，当前 URL: {page.url}）"
            ) from exc
        await fac_loc.first.click()
        log.info("[shipping] 已点击发货地 facility=%s", facility)
        await asyncio.sleep(0.2)
    else:
        log.info("[shipping] 无需选择 facility（auto_finish），直接点完了")

    # ── Step 5: 点「選択して完了する」──
    finish_btn = page.get_by_role("button", name=_SELECT_FINISH_BUTTON_TEXT)
    try:
        await finish_btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        finish_btn = page.locator(f'button:has-text("{_SELECT_FINISH_BUTTON_TEXT}")')
        try:
            await finish_btn.first.wait_for(state="visible", timeout=4000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_SELECT_FINISH_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc
    await finish_btn.first.click()
    log.info("[shipping] 已点击「%s」 account_id=%s", _SELECT_FINISH_BUTTON_TEXT, aid)

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "class_text": class_text,
        "facility": facility,
        "success": True,
    }


async def submit_transaction_review(todo_id: int, text: str) -> Dict[str, Any]:
    """在已打开的浏览器（取引評価页）填评价文本 + 点「購入者を評価して取引完了する」。

    页面上 ``良かった`` 通常默认选中，不需要再点。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    body = (text or "").strip()
    if not body:
        raise ValueError("评价文本不能为空")

    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    mgr = get_web_drive_manager()
    auto_key = meilu_automation_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「处理」打开交易页") from exc

    # 找到评价 textarea（按 placeholder）
    textarea = page.locator(
        f'textarea[placeholder="{_REVIEW_TEXTAREA_PLACEHOLDER}"]'
    )
    try:
        await textarea.first.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到评价输入框（placeholder 不匹配；当前 URL: {page.url}）"
        ) from exc
    await textarea.first.fill(body)
    log.info("[review] 已填入评价文本 text_len=%s", len(body))

    # 找到「購入者を評価して取引完了する」按钮
    btn = page.get_by_role("button", name=_REVIEW_SUBMIT_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        btn = page.locator(f'button:has-text("{_REVIEW_SUBMIT_BUTTON_TEXT}")')
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_REVIEW_SUBMIT_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc
    await btn.first.click()
    log.info(
        "[review] 已点击「%s」 account_id=%s",
        _REVIEW_SUBMIT_BUTTON_TEXT,
        aid,
    )

    # 二次确认弹窗：「購入者を評価して取引を完了しますか？」→ 点「取引を完了する」
    await asyncio.sleep(0.3)
    confirm_btn = page.get_by_role("button", name=_REVIEW_CONFIRM_BUTTON_TEXT)
    try:
        await confirm_btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        confirm_btn = page.locator(f'button:has-text("{_REVIEW_CONFIRM_BUTTON_TEXT}")')
        try:
            await confirm_btn.first.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到二次确认按钮「{_REVIEW_CONFIRM_BUTTON_TEXT}」（当前 URL: {page.url}）"
            ) from exc
    await confirm_btn.first.click()
    log.info(
        "[review] 已点击二次确认「%s」 account_id=%s",
        _REVIEW_CONFIRM_BUTTON_TEXT,
        aid,
    )

    # 等页面刷新 + 检测「取引が完了しました」文案
    completed = False
    try:
        completed_loc = page.get_by_text(_REVIEW_COMPLETED_TEXT, exact=False).first
        await completed_loc.wait_for(state="visible", timeout=15000)
        completed = True
        log.info("[review] 检测到「%s」 account_id=%s", _REVIEW_COMPLETED_TEXT, aid)
    except Exception:
        log.warning(
            "[review] 15s 内未检测到「%s」（可能已完成但页面文案变化；当前 URL: %s）",
            _REVIEW_COMPLETED_TEXT,
            page.url,
        )

    order_refresh_error: Optional[str] = None
    if completed:
        # 软删除本地 todo（页面已结案，对应煤炉端 todolist 也会下次同步剔除）
        try:
            todo.is_delete = 1
            todo.synced_at = int(time.time() * 1000)
            todo.save()
            log.info("[review] 已软删除 todo_id=%s", todo_id)
        except Exception as exc:
            log.warning("[review] 软删除 todo 失败: %s", exc)

        # 关浏览器
        try:
            await mgr.close_session_if_automation(auto_key)
            log.info("[review] 已关闭 __auto 浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[review] 关浏览器失败: %s", exc)

        # 刷新订单信息（按 item_id 等于 order_no 查 orders 表，回填 transaction_evidences 字段）
        if item_id:
            try:
                order_refresh_error = await apply_item_info_to_order(item_id, account_id=aid)
                if order_refresh_error:
                    log.warning("[review] 订单刷新返回错误: %s", order_refresh_error)
                else:
                    log.info("[review] 订单刷新完成 item_id=%s", item_id)
            except Exception as exc:
                order_refresh_error = f"exception:{exc}"
                log.warning("[review] 订单刷新异常: %s", exc)
        else:
            log.warning("[review] todo 无 item_id，跳过订单刷新")

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "submitted": True,
        "confirmed": True,
        "completed": completed,
        "order_refresh_error": order_refresh_error,
        "text_len": len(body),
    }


async def click_change_shipping_method(todo_id: int) -> Dict[str, Any]:
    """点 transaction 页的「発送方法を変更する」（导航到修改发送方式页；后续由用户在浏览器内手动）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)

    mgr = get_web_drive_manager()
    auto_key = meilu_automation_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「处理」打开交易页") from exc

    btn = page.get_by_role("button", name=_CHANGE_METHOD_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        btn = page.locator(f'button:has-text("{_CHANGE_METHOD_BUTTON_TEXT}")')
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_CHANGE_METHOD_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc
    await btn.first.click()
    log.info("[shipping] 已点击「%s」 account_id=%s", _CHANGE_METHOD_BUTTON_TEXT, aid)
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "clicked": True,
    }
