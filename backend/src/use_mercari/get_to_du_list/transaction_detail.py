# -*- coding: utf-8 -*-
"""
待办事项 →「处理」按钮：打开 https://jp.mercari.com/transaction/<item_id>，
通过 **MITM 抓两个关键 API** 还原交易详情字段（不再做 DOM 爬取）：

- GET ``api.mercari.jp/shipping/get_info?transaction_evidence_id=...``
  → 商品名、发送方法、发送元、shipment 状态
- GET ``api.mercari.jp/transaction_messages/get_messages?item_id=...``
  → 买家·卖家消息流（含用户名、时间）

直接使用账号主 profile ``mercari_{id}`` 打开浏览器（与 /mercari-accounts 「打开浏览器」
一致，登录态由 Edge 持久化 cookie 自动维护，不再用 ``__auto`` 副本 + seed cookie）。
浏览器在抓取后 **保持打开**，方便用户在原生页面上手动操作。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...db_manage.database import DatabaseManager
from ...db_manage.models.todo_item import TodoItemModel
from ...use_web.image_storage import save_image_bytes
from ...ssl_mitm_proxy.capture_config import (
    clear_shipping_info_response_file,
    clear_transaction_messages_response_file,
    read_shipping_info_response,
    read_transaction_messages_response,
)
from ...web_drive.core.manager import EdgeWebDriveManager, get_web_drive_manager
from ...web_drive.core.mitm_session import (
    _raise_login_required_for,
    login_redirect_state_for,
    mitm_automation_browser,
)
from ...web_drive.core.paths import mercari_account_key, mercari_id_from_account_key
from ..get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ..sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


# 「待发货」待办：处理时需打开持久化的有头浏览器（前台可见），便于用户在浏览器内
# 亲自核对/操作发货。kind 命中下列集合，或标题为「発送をしてください」即视为待发货。
_WAIT_SHIPPING_KINDS = frozenset(
    {
        "WaitShippingCard",
        "WaitShippingPoint",
        "WaitShippingCarrier",
        "TransactionWaitShippingFunds",
    }
)
_WAIT_SHIPPING_TITLE = "発送をしてください"

# 「待回复」待办：买家来信，处理面板展示消息流并回复。无需有头浏览器。
_WAIT_REPLY_KINDS = frozenset({"IncomingMessage"})


def _is_wait_shipping_todo(todo: Any) -> bool:
    kind = (getattr(todo, "kind", "") or "").strip()
    title = (getattr(todo, "title", "") or "").strip()
    return kind in _WAIT_SHIPPING_KINDS or title == _WAIT_SHIPPING_TITLE


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
    """同一轮询循环里等两个文件，避免互相干扰的 reload。

    每次迭代都会检查实时登录跳转监听器是否触发；命中则提前抛
    ``MercariLoginRequiredError``，不再等满 timeout。
    """
    aid_for_login = mercari_id_from_account_key(auto_key)
    deadline = time.monotonic() + timeout
    next_reload = time.monotonic() + _RELOAD_INTERVAL_SEC
    shipping: Optional[Dict[str, Any]] = None
    messages: Optional[Dict[str, Any]] = None
    while time.monotonic() < deadline:
        if aid_for_login is not None and login_redirect_state_for(aid_for_login):
            _raise_login_required_for(aid_for_login)
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
    if aid_for_login is not None and login_redirect_state_for(aid_for_login):
        _raise_login_required_for(aid_for_login)
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
        msg_id_raw = m.get("id")
        msg_id = str(msg_id_raw).strip() if msg_id_raw is not None else ""
        reaction = (m.get("reaction") or "").strip()
        out["messages"].append(
            {
                "id": msg_id or None,
                "from": (user.get("name") or "").strip() or None,
                "text": body_text,
                "at": _format_ts(m.get("created")),
                "is_buyer": is_buyer,
                "user_id": uid or None,
                "reaction": reaction or None,
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


async def fetch_transaction_detail(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
    force_headless: bool = False,
) -> Dict[str, Any]:
    """打开有头浏览器到 transaction 页 → MITM 等两个 API → 解析返回。

    ``force_headless``：批量预缓存（「从煤炉同步」后为无缓存的待发货待办补抓详情）场景用。
    待发货待办默认强制有头+前台可见，便于用户手动核对；但同步时若逐条弹出前台浏览器
    会非常干扰，故此参数为 True 时即便待发货也静默无头运行。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备煤炉账号…")
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

    # ── Step 1: 清空 latest 响应文件 + 取 since_ms ──
    clear_shipping_info_response_file()
    clear_transaction_messages_response_file()
    since_ms = int(time.time() * 1000)

    # ── Step 2: 用账号主 profile 经 MITM 打开交易页（与 /orders 更新列表同模式，
    #            cookie 由 Edge 持久化自动维护；浏览器留给后续 followup op 复用，
    #            队列空闲自动关闭由路由层 suppress_idle_close=True 关闭）──
    # 待发货待办：强制有头 + 前台可见的持久化浏览器，便于用户在浏览器内亲自核对发货；
    # 其余类型沿用默认（由 WEB_DRIVE_AUTOMATION_HEADLESS 决定，通常无头静默）。
    is_wait_shipping = _is_wait_shipping_todo(todo)
    if force_headless:
        # 同步后的批量预缓存：即便待发货也静默无头，避免逐条弹出前台浏览器
        headless_override = True
        minimized_override = True
    else:
        headless_override = False if is_wait_shipping else None
        minimized_override = False if is_wait_shipping else None
        if is_wait_shipping:
            log.info("[txdetail] 待发货待办 → 打开有头持久化浏览器 account_id=%s", aid)

    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=headless_override,
        minimized=minimized_override,
    ) as (mgr, main_key):
        report("wait_captures", "等待 shipping_info 与 transaction_messages 截获…")
        shipping, messages = await _wait_for_both_captures(
            mgr=mgr,
            auto_key=main_key,
            start_url=url,
            since_ms=since_ms,
        )
        # 同步发货码（QR 二维码 / らくらく×セブン等返回的条形码，二者通用同一处理）：
        # 交易页若带发货码（含在 App/其他平台已完成发货）→ 抓取保存；
        # 若页面确无发货码（别处取消/重置了发货）→ 后续清除本地已存的，回到选择发送状态。
        synced_qr_url: Optional[str] = None
        synced_facility: Dict[str, str] = {}
        qr_checked = False
        qr_present = False
        try:
            qr_page = await mgr.active_tab_page(main_key)
            qr_present = await _qr_code_exists(qr_page, timeout=3000)
            qr_checked = True
            if qr_present:
                synced_qr_url = await _save_qr_code_image(
                    qr_page, item_id=item_id, todo_id=int(todo_id), timeout=1500
                )
                # 同步「発送場所」信息（标题/说明/图标），供前端在发货码旁展示
                synced_facility = await _extract_shipping_facility(qr_page)
        except Exception as exc:
            log.debug("[txdetail] 同步发货二维码失败 todo_id=%s: %s", todo_id, exc)

    if shipping is None and messages is None:
        log.warning("[txdetail] 两个 API 均未截获 todo_id=%s", todo_id)
    elif shipping is None:
        log.warning("[txdetail] shipping/get_info 未截获 todo_id=%s", todo_id)
    elif messages is None:
        log.warning("[txdetail] transaction_messages/get_messages 未截获 todo_id=%s", todo_id)

    report("parse_response", "正在解析截获的取引详情…")
    shipping_part = _parse_shipping_info(shipping, local_sender_id)
    messages_part = _parse_messages(messages, local_sender_id)

    result = {
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
    # 发货二维码同步：
    #   - 本次抓到 → 用新的
    #   - 页面已加载且确无二维码（别处取消/重置发货）→ 清除本地已存的，回到选择发送状态
    #   - 检查失败/页面未加载（保守）→ 沿用此前已保存的
    page_loaded = (shipping is not None) or (messages is not None)
    if synced_qr_url:
        result["qr_image_url"] = synced_qr_url
        # 发货码存在时，附带本次抓到的发送场所信息（标题/说明/图标）
        if synced_facility:
            result.update(synced_facility)
    elif qr_checked and not qr_present and page_loaded:
        _clear_qr_image(int(todo_id))
        result["qr_image_url"] = None
    else:
        try:
            prev = DatabaseManager().execute_query(
                "SELECT [qr_image_path], [detail_json] FROM [todo_items] WHERE [id]=?",
                (int(todo_id),),
            )
            if prev and prev[0]:
                if prev[0][0]:
                    result["qr_image_url"] = prev[0][0]
                # 保留此前缓存的发送场所信息（_persist_transaction_detail 会整体覆盖）
                if prev[0][1]:
                    try:
                        pd = json.loads(prev[0][1])
                        if isinstance(pd, dict):
                            for k in (
                                "shipping_facility_name",
                                "shipping_facility_desc",
                                "shipping_facility_image_url",
                            ):
                                if pd.get(k) and not result.get(k):
                                    result[k] = pd[k]
                    except Exception:
                        pass
        except Exception:
            pass
    _persist_transaction_detail(int(todo_id), result)

    report("done", "交易详情已就绪")
    return result


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
    auto_key = mercari_account_key(aid)

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


# ====================================================================
# 选择商品尺寸与发送地
# ====================================================================

_SIZE_SELECT_BUTTON_TEXT = "商品サイズと発送場所を選択する"
_CHANGE_METHOD_BUTTON_TEXT = "発送方法を変更する"
# /shipping_method 页：配送方式 radio 的 name 与确认按钮文本
_CHANGE_METHOD_RADIO_NAME = "shippingClass"
_CHANGE_METHOD_SUBMIT_TEXT = "変更する"
_SELECT_NEXT_BUTTON_TEXT = "選択して次へ"
_SELECT_FINISH_BUTTON_TEXT = "選択して完了する"
# ゆうパケットポスト / ゆうパケットポストmini 完了後、交易ページに出る「2次元コードを読み取る」
# （这是“调用摄像头扫描”的入口，仅 ゆうパケットポスト系 使用）
_SCAN_QR_BUTTON_TEXT = "2次元コードを読み取る"
# 除 ゆうパケットポスト系 之外（需选发货地的方法）：完了後、交易ページで发行 发送用 QR/条形码/二维码
# （无需摄像头，卖家拿生成的码到店扫描）。文言随发货地/方法不同，列出候选逐个尝试。
_GENERATE_SHIP_CODE_TEXTS = (
    "発送用2次元コードを発行",
    "発送用QRコードを発行",
    "発送用バーコードを発行",
)
# /qr_code_scanner 上の撮影開始ボタン（カメラ無効時は disabled）
_SCAN_START_BUTTON_TEXT = "QRコードをスキャンする"
# 読み取り成功後の交易ページ上の発送確定 UI
_SCAN_OK_TEXT = "読み取りが正しく完了しました"
# 確認用チェックボックスのラベル候補（シール/専用箱など発送方法で文言が変わるため複数許容）
_SHIP_CONFIRM_CHECKBOX_TEXTS = (
    "ご依頼主様控えを切り取りました",
    "梱包した商品に発送用シールを貼りました",
)
_NOTIFY_SHIP_BUTTON_TEXT = "商品を発送したので、発送通知をする"
_SHIPPED_CONFIRM_BUTTON_TEXT = "発送しました"
# 二次确认後、页面が再読込され発送完了になると表示される文言
_SHIP_SUCCESS_TEXT = "購入者の受取をお待ちください"

# ─── 远程摄像头注入 ───────────────────────────────────────────────
# 服务器没有摄像头：在 QR スキャナページに入る前に、navigator.mediaDevices の
# getUserMedia / enumerateDevices を差し替え、canvas.captureStream() を「カメラ」として返す。
# 客户端（管理 UI を開いているユーザー端末）のカメラ映像を window.__pushCameraFrame(dataUrl,w,h)
# で逐次この canvas に描画 → スキャナはあたかもローカルカメラがあるかのように QR を読み取る。
_FAKE_CAMERA_JS = r"""
(() => {
  try {
    if (window.__remoteCamInstalled) return true;
    window.__remoteCamInstalled = true;
    var canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 480;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    var stream = null;
    window.__remoteCamCanvas = canvas;
    window.__pushCameraFrame = function (dataUrl, w, h) {
      try {
        if (!dataUrl) return false;
        var img = new Image();
        img.onload = function () {
          try {
            if (w && h && (canvas.width !== w || canvas.height !== h)) {
              canvas.width = w; canvas.height = h;
            }
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          } catch (e) {}
        };
        img.src = dataUrl;
        return true;
      } catch (e) { return false; }
    };
    function getStream() {
      if (!stream) { stream = canvas.captureStream(30); }
      return stream;
    }
    if (!navigator.mediaDevices) { try { navigator.mediaDevices = {}; } catch (e) {} }
    var md = navigator.mediaDevices;
    if (md) {
      var origGUM = md.getUserMedia ? md.getUserMedia.bind(md) : null;
      md.getUserMedia = function (constraints) {
        if (constraints && constraints.video) {
          try { return Promise.resolve(getStream()); } catch (e) { return Promise.reject(e); }
        }
        return origGUM ? origGUM(constraints) : Promise.reject(new Error('no media'));
      };
      var origEnum = md.enumerateDevices ? md.enumerateDevices.bind(md) : null;
      md.enumerateDevices = function () {
        var fake = { deviceId: 'remote-virtual-cam', kind: 'videoinput', label: 'Remote Camera', groupId: 'remote' };
        fake.toJSON = function () { return this; };
        if (origEnum) {
          return origEnum().then(function (list) {
            var others = (list || []).filter(function (d) { return d.kind !== 'videoinput'; });
            return [fake].concat(others);
          }).catch(function () { return [fake]; });
        }
        return Promise.resolve([fake]);
      };
    }
    return true;
  } catch (e) { return false; }
})();
"""


async def start_select_shipping_class(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「商品サイズと発送場所を選択する」按钮 → 等浏览器跳到 /shipping_class。

    尺寸列表由前端硬编码（按 shipping_method_name 区分），不再依赖 MITM 抓取。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"

    # 点「处理」不再自动开浏览器，因此本操作需自行确保浏览器已打开并停在交易页。
    # mitm_automation_browser 已开则复用并 reload 到交易页，未开则启动；退出不关闭。
    is_wait_shipping = _is_wait_shipping_todo(todo)
    headless_override = False if is_wait_shipping else None
    minimized_override = False if is_wait_shipping else None
    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=headless_override,
        minimized=minimized_override,
    ) as (mgr, auto_key):
        page = await mgr.active_tab_page(auto_key)

        report("locate_button", "正在定位「商品サイズと発送場所を選択する」按钮…")
        btn = page.get_by_role("button", name=_SIZE_SELECT_BUTTON_TEXT)
        try:
            await btn.first.wait_for(state="visible", timeout=8000)
        except Exception:
            btn = page.locator(f'button:has-text("{_SIZE_SELECT_BUTTON_TEXT}")')
            try:
                await btn.first.wait_for(state="visible", timeout=4000)
            except Exception as exc:
                raise RuntimeError(
                    f"未找到「{_SIZE_SELECT_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
                ) from exc
        report("click_button", "正在点击按钮，等待跳转到 /shipping_class…")
        await btn.first.click()
        log.info("[shipping] 已点击「%s」 account_id=%s", _SIZE_SELECT_BUTTON_TEXT, aid)

        # 等浏览器跳到 /shipping_class（用户后续在我们 dialog 内选 size）
        try:
            await page.wait_for_url("**/shipping_class*", timeout=8000)
        except Exception:
            log.warning("[shipping] 未观察到 /shipping_class 导航（可能已经在该页）")

    report("done", "已进入「商品サイズと発送場所」选择页")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "clicked": True,
    }


# 旧式（ゆうゆうメルカリ便 郵便局/ローソン）：XPath 卡片点击，保持向后兼容
_FACILITY_XPATHS = {
    "post_office": '//*[@id="main"]/div/form/div[1]/div/div[1]/div/div[1]',
    "lawson": '//*[@id="main"]/div/form/div[1]/div/div[1]/div/div[2]',
}

# 新式：/shipping_facilities 页 radio 卡片用 input[value] 选择（语言无关、最稳）
# 前端按尺寸下发对应 facility code（与煤炉 radio 的 value 属性一致）：
#   SEVEN_ELEVEN / FAMILY_MART / YAMATO_OFFICE / PUDO / POST_OFFICE / LAWSON / ...
_FACILITY_ARIA_LABELS = {
    "SEVEN_ELEVEN": "セブン-イレブン",
    "FAMILY_MART": "ファミリーマート",
    "YAMATO_OFFICE": "ヤマト運輸 営業所",
    "PUDO": "宅配便ロッカーPUDO",
}


async def _click_scan_qr_and_open_scanner(
    page: Any,
    *,
    item_id: str,
    report,
) -> bool:
    """交易ページに戻った後「2次元コードを読み取る」を押して /qr_code_scanner へ遷移。

    成功で True。ボタンが無い（既に発送済み等）場合は False を返す。
    """
    # 完了する後、交易ページ /transaction/{item_id} に戻るのを待つ
    try:
        await page.wait_for_url("**/transaction/*", timeout=10000)
    except Exception:
        log.warning("[shipping] 完了後に交易ページへ戻る遷移を観測できず (URL: %s)", page.url)
    # SPA 再描画待ち
    await asyncio.sleep(0.6)

    # 远程摄像头注入：服务器无摄像头 → 把「客户端推送的帧」当作本地摄像头喂给 QR スキャナ。
    # ・add_init_script: ハードナビゲーション（新ドキュメント）に効く
    # ・evaluate: SPA ソフトナビ（同一ドキュメント内でルート遷移）に効く
    # スキャナページがマウント時に enumerateDevices を見るため、遷移「前」に仕込む。
    try:
        await page.add_init_script(_FAKE_CAMERA_JS)
    except Exception as exc:
        log.debug("[qrcam] add_init_script 失敗: %s", exc)
    try:
        await page.evaluate(_FAKE_CAMERA_JS)
    except Exception as exc:
        log.debug("[qrcam] evaluate 注入失敗: %s", exc)

    report("click_scan_qr", "正在点击「2次元コードを読み取る」…")
    scan_btn = page.get_by_role("button", name=_SCAN_QR_BUTTON_TEXT)
    try:
        await scan_btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        scan_btn = page.locator(f'button:has-text("{_SCAN_QR_BUTTON_TEXT}")')
        try:
            await scan_btn.first.wait_for(state="visible", timeout=4000)
        except Exception:
            log.warning(
                "[shipping] 「%s」ボタンが見つからず (URL: %s)",
                _SCAN_QR_BUTTON_TEXT,
                page.url,
            )
            return False
    await scan_btn.first.click()
    log.info("[shipping] 已点击「%s」", _SCAN_QR_BUTTON_TEXT)
    try:
        await page.wait_for_url("**/qr_code_scanner*", timeout=8000)
    except Exception:
        log.warning("[shipping] /qr_code_scanner への遷移を観測できず (URL: %s)", page.url)

    # スキャナ到達後：念のため再注入（ソフトナビ後でも window に効くよう）し、
    # 撮影開始ボタン「QRコードをスキャンする」が有効なら押してカメラを起動させる。
    await asyncio.sleep(0.6)
    try:
        await page.evaluate(_FAKE_CAMERA_JS)
    except Exception:
        pass
    try:
        start_btn = page.get_by_role("button", name=_SCAN_START_BUTTON_TEXT)
        if await start_btn.count() == 0:
            start_btn = page.locator(f'button:has-text("{_SCAN_START_BUTTON_TEXT}")')
        if await start_btn.count() > 0:
            b = start_btn.first
            if await b.is_visible() and await b.is_enabled():
                await b.click()
                log.info("[qrcam] 已点击「%s」启动摄像头", _SCAN_START_BUTTON_TEXT)
    except Exception as exc:
        log.debug("[qrcam] 開始ボタン押下スキップ: %s", exc)
    return True


async def push_remote_camera_frame(
    todo_id: int,
    *,
    frame: str = "",
    width: int = 0,
    height: int = 0,
) -> Dict[str, Any]:
    """客户端摄像头帧 → 注入到有头浏览器的「虚拟摄像头」canvas（QR スキャナ用）。

    返回值同时携带扫描状态，供前端判断是否停止推流：
      - ``on_scanner``: 仍在 /qr_code_scanner（继续推流）
      - ``done``: 已离开扫描页回到 /transaction/（读取成功）
      - ``pushed``: 本帧是否成功写入页面 canvas
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    url = ""
    try:
        url = (page.url or "").strip()
    except Exception:
        url = ""
    on_scanner = "/qr_code_scanner" in url
    done = (not on_scanner) and "/transaction/" in url

    pushed = False
    if frame and on_scanner:
        try:
            pushed = bool(
                await page.evaluate(
                    "(a) => (typeof window.__pushCameraFrame === 'function')"
                    " ? window.__pushCameraFrame(a.f, a.w, a.h) : false",
                    {"f": frame, "w": int(width or 0), "h": int(height or 0)},
                )
            )
        except Exception as exc:
            log.debug("[qrcam] フレーム注入失敗: %s", exc)

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "on_scanner": on_scanner,
        "done": done,
        "url": url,
        "pushed": pushed,
    }


# 交易ページ上の発送用コード画像（発行後に表示される）。
# QRコード（2次元コード）は data-testid="qr-code"、らくらくメルカリ便×セブン-イレブン等で
# 返るバーコードは data-testid="bar-code"。两者都要匹配。
_QR_CODE_IMG_SELECTOR = 'img[data-testid="qr-code"], img[data-testid="bar-code"]'


def _persist_transaction_detail(todo_id: int, data: Dict[str, Any]) -> None:
    """把抓取到的交易详情整体缓存进 todo_items.detail_json（避免每次开浏览器重抓）。"""
    try:
        payload = json.dumps(data, ensure_ascii=False)
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [detail_json]=?, [detail_synced_at]=? WHERE [id]=?",
            (payload, int(time.time() * 1000), int(todo_id)),
        )
    except Exception as exc:
        log.warning("[txdetail] 缓存交易详情失败 todo_id=%s: %s", todo_id, exc)


def _persist_qr_image_path(todo_id: int, path: str) -> None:
    """保存二维码本地路径到 todo_items.qr_image_path，并同步写入已缓存的 detail_json。"""
    db = DatabaseManager()
    try:
        db.execute_update(
            "UPDATE [todo_items] SET [qr_image_path]=? WHERE [id]=?", (path, int(todo_id))
        )
        rows = db.execute_query(
            "SELECT [detail_json] FROM [todo_items] WHERE [id]=?", (int(todo_id),)
        )
        if rows and rows[0] and rows[0][0]:
            d = json.loads(rows[0][0])
            if isinstance(d, dict):
                d["qr_image_url"] = path
                db.execute_update(
                    "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                    (json.dumps(d, ensure_ascii=False), int(todo_id)),
                )
    except Exception as exc:
        log.warning("[shipping] 保存二维码路径失败 todo_id=%s: %s", todo_id, exc)


def _clear_qr_image(todo_id: int) -> None:
    """清除已保存的发货二维码：删除本地文件 + 清空 qr_image_path + 从 detail_json 摘掉。"""
    db = DatabaseManager()
    try:
        rows = db.execute_query(
            "SELECT [qr_image_path], [detail_json] FROM [todo_items] WHERE [id]=?",
            (int(todo_id),),
        )
        old_path = rows[0][0] if rows and rows[0] else None
        detail_json = rows[0][1] if rows and rows[0] else None
        db.execute_update(
            "UPDATE [todo_items] SET [qr_image_path]=NULL WHERE [id]=?", (int(todo_id),)
        )
        if detail_json:
            try:
                d = json.loads(detail_json)
                if isinstance(d, dict) and d.pop("qr_image_url", None) is not None:
                    db.execute_update(
                        "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                        (json.dumps(d, ensure_ascii=False), int(todo_id)),
                    )
            except Exception:
                pass
        if old_path:
            try:
                from ...use_web.image_storage import delete_image_file

                delete_image_file(old_path)
            except Exception:
                pass
    except Exception as exc:
        log.warning("[shipping] 清除二维码失败 todo_id=%s: %s", todo_id, exc)


def get_cached_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """读取 todo_items.detail_json 缓存（无浏览器）。无缓存返回 {}（仅含基础字段）。"""
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [detail_json], [detail_synced_at], [qr_image_path], [item_id], [item_name], [sender_id] "
            "FROM [todo_items] WHERE [id]=?",
            (int(todo_id),),
        )
    except Exception as exc:
        log.warning("[txdetail] 读取交易详情缓存失败 todo_id=%s: %s", todo_id, exc)
        return {}
    if not rows:
        return {}
    detail_json, synced_at, qr_path, item_id, item_name, sender_id = rows[0]
    data: Dict[str, Any] = {}
    if detail_json:
        try:
            parsed = json.loads(detail_json)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    data.setdefault("item_id", item_id or "")
    data.setdefault("item_name", item_name or "")
    data.setdefault("sender_id", sender_id or "")
    data["detail_synced_at"] = synced_at
    if qr_path and not data.get("qr_image_url"):
        data["qr_image_url"] = qr_path
    return data


def list_uncached_detail_todo_ids(account_id: int) -> List[int]:
    """返回某账号下「待发货」或「待回复」且尚无交易详情缓存的待办 id（供「从煤炉同步」后批量补抓详情）。

    判定「无缓存」：``detail_synced_at IS NULL``（fetch_transaction_detail 成功后才会写入）。
    仅含未软删 + 有 item_id 的待办（无 item_id 无法打开交易页）。
    """
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [id], [kind], [title] FROM [todo_items] "
            "WHERE [account_id]=? AND [is_delete]=0 "
            "AND [detail_synced_at] IS NULL "
            "AND [item_id] IS NOT NULL AND TRIM([item_id]) <> '' "
            "ORDER BY [mercari_updated] DESC",
            (int(account_id),),
        )
    except Exception as exc:
        log.warning("[txdetail] 查询未缓存待办失败 account_id=%s: %s", account_id, exc)
        return []
    ids: List[int] = []
    for row in rows or []:
        tid, kind, title = row
        kind = (kind or "").strip()
        title = (title or "").strip()
        if (
            kind in _WAIT_SHIPPING_KINDS
            or kind in _WAIT_REPLY_KINDS
            or title == _WAIT_SHIPPING_TITLE
        ):
            ids.append(int(tid))
    return ids


async def _qr_code_exists(page: Any, *, timeout: int = 3000) -> bool:
    """快速判断交易页上是否存在发货码图片（已发行）。兼容 QR 二维码与条形码。"""
    try:
        await page.locator(_QR_CODE_IMG_SELECTOR).first.wait_for(
            state="visible", timeout=timeout
        )
        return True
    except Exception:
        return False


async def _save_qr_code_image(
    page: Any, *, item_id: str, todo_id: int, timeout: int = 8000
) -> Optional[str]:
    """把交易页上的发货码图片下载到本地，返回 /imges 路径。

    兼容 QR 二维码（data-testid="qr-code"）与らくらく×セブン-イレブン等返回的条形码
    （data-testid="bar-code"）——见 ``_QR_CODE_IMG_SELECTOR``。

    ``timeout``：等待发货码出现的毫秒数。发行后流程用默认 8s；刷新抓取/同步场景
    传较短值（页面已加载，有就立刻拿到，没有则快速返回 None）。
    """
    try:
        img = page.locator(_QR_CODE_IMG_SELECTOR)
        await img.first.wait_for(state="visible", timeout=timeout)
        src = await img.first.get_attribute("src")
    except Exception:
        log.debug("[shipping] 交易页无发货二维码 (item_id=%s)", item_id)
        return None
    if not src:
        return None
    try:
        resp = await page.request.get(src)
        body = await resp.body()
    except Exception as exc:
        log.warning("[shipping] 下载二维码图片失败 src=%s: %s", src, exc)
        return None
    low = src.lower()
    ext = "jpg" if (".jpg" in low or ".jpeg" in low) else "png"
    try:
        path = save_image_bytes(body, ext=ext, prefix=f"qr_{item_id}")
    except Exception as exc:
        log.warning("[shipping] 保存二维码图片失败: %s", exc)
        return None
    _persist_qr_image_path(int(todo_id), path)
    log.info("[shipping] 已保存发货二维码 todo_id=%s path=%s", todo_id, path)
    return path


# 交易页发货码上方的「○○から発送」信息：标题（如「ファミリーマートから発送」）、
# 说明文、以及发送场所图标 URL（煤炉 CDN img[src*="shipping_facility"]，如
# family-mart.png / seven-eleven.png / yamato.png / pudo.png）。供前端在发货码旁
# 展示「发送场所 + 图标」。兼容 ファミリーマート/セブン-イレブン/ヤマト営業所/PUDO 等。
_SHIPPING_FACILITY_JS = """
() => {
  const pick = (el) => (el && el.innerText ? el.innerText.trim() : '');
  const titleEl = document.querySelector('[data-testid="qrcode.title"]');
  let title = pick(titleEl);
  let desc = '';
  if (titleEl) {
    let n = titleEl.nextElementSibling;
    while (n) {
      if (n.tagName === 'P') { desc = pick(n); break; }
      if (n.querySelector && n.querySelector('img')) break;
      n = n.nextElementSibling;
    }
  }
  const img = document.querySelector('img[src*="shipping_facility"]');
  const imageUrl = img ? (img.currentSrc || img.src || '') : '';
  return { title, desc, imageUrl };
}
"""


async def _extract_shipping_facility(page: Any) -> Dict[str, str]:
    """从交易页提取「発送場所」展示信息（标题/说明/图标 URL）。无则返回 {}。"""
    try:
        data = await page.evaluate(_SHIPPING_FACILITY_JS)
    except Exception as exc:
        log.debug("[shipping] 提取发送场所信息失败: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    title = (data.get("title") or "").strip()
    desc = (data.get("desc") or "").strip()
    image_url = (data.get("imageUrl") or "").strip()
    if title:
        out["shipping_facility_name"] = title
    if desc:
        out["shipping_facility_desc"] = desc
    if image_url:
        out["shipping_facility_image_url"] = image_url
    return out


def _persist_shipping_facility(todo_id: int, fac: Dict[str, str]) -> None:
    """把发送场所信息合并进 todo_items.detail_json（不覆盖其它字段）。"""
    if not fac:
        return
    db = DatabaseManager()
    try:
        rows = db.execute_query(
            "SELECT [detail_json] FROM [todo_items] WHERE [id]=?", (int(todo_id),)
        )
        d: Dict[str, Any] = {}
        if rows and rows[0] and rows[0][0]:
            try:
                parsed = json.loads(rows[0][0])
                if isinstance(parsed, dict):
                    d = parsed
            except Exception:
                d = {}
        d.update(fac)
        db.execute_update(
            "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
            (json.dumps(d, ensure_ascii=False), int(todo_id)),
        )
    except Exception as exc:
        log.warning("[shipping] 缓存发送场所信息失败 todo_id=%s: %s", todo_id, exc)


async def _click_generate_ship_code(
    page: Any,
    *,
    item_id: str,
    todo_id: int,
    report,
) -> Optional[str]:
    """完了後、交易ページに戻り「発送用2次元コード/QRコード/バーコードを発行」を押す。

    需选发货地的方法（ゆうパケットポスト系以外）走此分支：无需摄像头，
    生成发送用码供卖家到店出示。点击发行后页面刷新出二维码 → 下载保存到本地，
    返回 /imges 路径；找不到二维码则返回 None。
    """
    try:
        await page.wait_for_url("**/transaction/*", timeout=10000)
    except Exception:
        log.warning("[shipping] 完了後に交易ページへ戻る遷移を観測できず (URL: %s)", page.url)
    await asyncio.sleep(0.6)

    report("generate_ship_code", "正在生成发送用二维码…")
    clicked = False
    for text in _GENERATE_SHIP_CODE_TEXTS:
        btn = page.get_by_role("button", name=text)
        try:
            if await btn.count() == 0:
                btn = page.locator(f'button:has-text("{text}")')
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click()
                log.info("[shipping] 已点击「%s」 item_id=%s", text, item_id)
                clicked = True
                break
        except Exception as exc:
            log.debug("[shipping] 生成ボタン「%s」押下スキップ: %s", text, exc)
    if clicked:
        # 点击发行后页面刷新出二维码，稍等渲染
        await asyncio.sleep(1.0)
    else:
        log.info("[shipping] 未找到「発送用…を発行」按钮，可能已发行，直接尝试抓取二维码")

    # 保存发货二维码（已发行/刚发行都尝试）
    report("save_qr_image", "正在保存发货二维码…")
    path = await _save_qr_code_image(page, item_id=item_id, todo_id=int(todo_id))
    if path:
        # 同时抓取「発送場所」信息（标题/说明/图标），合并进缓存供前端展示
        _persist_shipping_facility(int(todo_id), await _extract_shipping_facility(page))
    return path


async def confirm_shipping_selection(
    todo_id: int,
    class_text: str,
    facility: Optional[str] = None,
    *,
    scan_qr: bool = False,
    generate_code: bool = False,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在 /shipping_class 页选 size → 次へ → 在 /shipping_facilities 页按需点 facility → 完了する。

    ``facility``：
      - ``None``：不点 facility（用于 POST_BOX 唯一选项的 size，页面会自动选好）
      - ``"post_office"`` / ``"lawson"``：按对应 XPath 点击卡片
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    class_text = (class_text or "").strip()
    if not class_text:
        raise ValueError("class_text 不能为空")
    facility = (facility or "").strip() or None

    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    report("attach_browser", "正在连接已打开的浏览器…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    # ── Step 1: 按精确文本匹配点击 size ──
    report("select_size", f"正在选择尺寸「{class_text}」…")
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
    report("click_next", "正在点击「選択して次へ」…")
    next_btn = page.get_by_role("button", name=_SELECT_NEXT_BUTTON_TEXT)
    try:
        await next_btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        next_btn = page.locator(f'button:has-text("{_SELECT_NEXT_BUTTON_TEXT}")')
        await next_btn.first.wait_for(state="visible", timeout=4000)
    await next_btn.first.click()
    log.info("[shipping] 已点击「%s」 account_id=%s", _SELECT_NEXT_BUTTON_TEXT, aid)

    # ── Step 3: 等浏览器跳到 /shipping_facilities ──
    report("wait_facilities", "等待跳转到 /shipping_facilities…")
    try:
        await page.wait_for_url("**/shipping_facilities*", timeout=10000)
    except Exception:
        log.warning("[shipping] 未观察到 /shipping_facilities 导航 (当前 URL: %s)", page.url)

    # ── Step 4: 按需点 facility 卡片 ──
    # /shipping_facilities 页 radio 的 value 属性是稳定且语言无关的（POST_OFFICE / LAWSON /
    # SEVEN_ELEVEN / FAMILY_MART / YAMATO_OFFICE / PUDO ...）。优先按 value 选中，
    # 再回落到 aria-label（role=radio），最后回落旧式 XPath（兼容历史 post_office/lawson）。
    if facility is not None:
        report("select_facility", f"正在选择发货地（{facility}）…")
        code = facility.strip()
        picked = False
        # 优先：按 radio 的 value 属性选中（force 兼容 styled-components 隐藏 input）
        fac_input = page.locator(f'input[type="radio"][value="{code}"]')
        try:
            await fac_input.first.wait_for(state="attached", timeout=8000)
            await fac_input.first.check(force=True)
            picked = True
        except Exception as exc:
            log.debug("[shipping] value 选中发货地失败 facility=%s: %s", code, exc)
        # 回落 1：按 aria-label（role=radio）点击卡片
        if not picked:
            label = _FACILITY_ARIA_LABELS.get(code, code)
            try:
                fac_role = page.get_by_role("radio", name=label)
                await fac_role.first.click(force=True)
                picked = True
            except Exception as exc:
                log.debug("[shipping] aria-label 选中发货地失败 facility=%s: %s", code, exc)
        # 回落 2：旧式 XPath（向后兼容历史 post_office/lawson 小写 code）
        if not picked:
            xpath_expr = _FACILITY_XPATHS.get(code.lower())
            if xpath_expr:
                try:
                    fac_loc = page.locator(f"xpath={xpath_expr}")
                    await fac_loc.first.wait_for(state="visible", timeout=4000)
                    await fac_loc.first.click()
                    picked = True
                except Exception as exc:
                    log.debug("[shipping] XPath 选中发货地失败 facility=%s: %s", code, exc)
        if not picked:
            raise RuntimeError(
                f"未找到发货地选项（facility={facility}，当前 URL: {page.url}）"
            )
        log.info("[shipping] 已点击发货地 facility=%s", facility)
        await asyncio.sleep(0.2)
    else:
        log.info("[shipping] 无需选择 facility（auto_finish），直接点完了")

    # ── Step 5: 点「選択して完了する」──
    report("click_finish", "正在点击「選択して完了する」…")
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

    # ── Step 6: 完了後の分岐 ──
    #   scan_qr=True（ゆうパケットポスト系）：摄像头扫描 → /qr_code_scanner
    #   generate_code=True（需选发货地的方法）：返回交易ページ发行 发送用 QR/条形码（无需摄像头）
    qr_scanner_open = False
    ship_code_generated = False
    qr_image_url: Optional[str] = None
    item_id = (todo.item_id or "").strip()
    if scan_qr:
        qr_scanner_open = await _click_scan_qr_and_open_scanner(
            page, item_id=item_id, report=report,
        )
    elif generate_code:
        qr_image_url = await _click_generate_ship_code(
            page, item_id=item_id, todo_id=int(todo_id), report=report,
        )
        ship_code_generated = qr_image_url is not None

    report("done", "已完成发货尺寸与发货地选择")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "class_text": class_text,
        "facility": facility,
        "success": True,
        "qr_scanner_open": qr_scanner_open,
        "ship_code_generated": ship_code_generated,
        "qr_image_url": qr_image_url,
    }


async def capture_qr_scanner_frame(todo_id: int) -> Dict[str, Any]:
    """QR スキャナ（/qr_code_scanner）を開いている有頭ブラウザの現在タブを
    JPEG スクリーンショットで取得し、base64 で返す（管理 UI へミラー表示用）。

    返り値:
      - ``frame``: data URI 文字列（``data:image/jpeg;base64,...``）。取得不可なら None
      - ``on_scanner``: 現在 /qr_code_scanner 上にいるか
      - ``done``: スキャン完了（/qr_code_scanner を離れ /transaction/ に戻った）
      - ``url``: 現在 URL
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    url = ""
    try:
        url = (page.url or "").strip()
    except Exception:
        url = ""
    on_scanner = "/qr_code_scanner" in url
    # スキャナを開いた後にスキャナを離れて transaction に戻った＝読み取り成功とみなす
    done = (not on_scanner) and "/transaction/" in url

    frame = None
    try:
        import base64

        # 摄像头/取景框のみを切り出す（ページ全体・ヘッダ・余白は不要）。
        # 取れない時のみページ全体にフォールバック。
        shot = None
        for sel in ('[data-testid="qr-code-scanner-from-camera"]', "#video"):
            try:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    shot = await loc.first.screenshot(type="jpeg", quality=55)
                    break
            except Exception:
                continue
        if shot is None:
            shot = await page.screenshot(type="jpeg", quality=55)
        frame = "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii")
    except Exception as exc:
        log.debug("[qrscan] スクリーンショット取得失敗: %s", exc)

    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "frame": frame,
        "on_scanner": on_scanner,
        "done": done,
        "url": url,
    }


async def read_post_shipping_confirm_info(todo_id: int) -> Dict[str, Any]:
    """QR 読み取り成功後、交易ページに表示される確認情報を読み取って返す。

    返り値:
      - ``ok``: 「読み取りが正しく完了しました」が表示されているか
      - ``confirm_code``: ポスト発送確認符号（例: BE08TF）
      - ``tracking_no``: 追跡番号（例: 647528803213）
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    # SPA 再描画待ち（スキャン直後に取ると未反映の場合がある）
    text = ""
    for _ in range(12):
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if _SCAN_OK_TEXT in text or "発送確認符号" in text or "追跡番号" in text:
            break
        await asyncio.sleep(0.4)

    ok = _SCAN_OK_TEXT in text
    confirm_code = None
    m = re.search(r"発送確認符号[\s:：]*([A-Za-z0-9]+)", text)
    if m:
        confirm_code = m.group(1)
    tracking_no = None
    m = re.search(r"追跡番号[\s:：]*([0-9\-]+)", text)
    if m:
        tracking_no = m.group(1)

    log.info(
        "[postship] 読み取り情報 ok=%s code=%s tracking=%s todo=%s",
        ok, confirm_code, tracking_no, todo_id,
    )
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "ok": ok,
        "confirm_code": confirm_code,
        "tracking_no": tracking_no,
    }


async def _tick_ship_confirm_checkboxes(page: Any) -> int:
    """発送確認ページのチェックボックスにチェックを入れる（複数文言・構造に対応）。

    1) ラベル文言を含む要素の祖先 ``<label>`` をクリック（無ければその要素を直接クリック）
    2) 取りこぼした ``input[type=checkbox]`` を force でチェック
    戻り値: チェック/クリックできた数。
    """
    ticked = 0
    for label_text in _SHIP_CONFIRM_CHECKBOX_TEXTS:
        try:
            loc = page.get_by_text(label_text, exact=False)
            if await loc.count() == 0:
                continue
        except Exception:
            continue
        clicked = False
        # チェックボックスの toggle 範囲＝<label>。あればそれをクリック
        try:
            lbl = loc.first.locator("xpath=ancestor-or-self::label[1]")
            if await lbl.count() > 0:
                await lbl.first.click(timeout=3000)
                clicked = True
        except Exception:
            clicked = False
        if not clicked:
            try:
                await loc.first.click(timeout=3000)
                clicked = True
            except Exception:
                clicked = False
        if clicked:
            ticked += 1
            log.info("[postship] チェック「%s」", label_text)
            await asyncio.sleep(0.2)

    # 取りこぼし対策：未チェックの checkbox を force でチェック
    try:
        cbs = page.locator('input[type="checkbox"]')
        cnt = await cbs.count()
        for i in range(cnt):
            cb = cbs.nth(i)
            try:
                if not await cb.is_checked():
                    await cb.check(force=True, timeout=1500)
                    ticked += 1
                    log.info("[postship] force-checked checkbox[%d]", i)
            except Exception:
                pass
    except Exception:
        pass
    return ticked


async def _click_visible_button_by_text(page: Any, text: str, *, timeout_ms: int = 8000) -> bool:
    """可視かつ有効な「text」ボタンを探してクリック（モーダル内のボタンも対象）。

    role=button → ``button:has-text`` の順で候補を集め、**非表示の複製（portal/template）を
    避けるため可視・有効なものだけ**をクリックする。出現するまで短間隔でポーリング。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for loc in (
            page.get_by_role("button", name=text),
            page.locator(f'button:has-text("{text}")'),
        ):
            try:
                n = await loc.count()
            except Exception:
                n = 0
            for i in range(n):
                b = loc.nth(i)
                try:
                    if await b.is_visible() and await b.is_enabled():
                        await b.click()
                        return True
                except Exception:
                    continue
        await asyncio.sleep(0.3)
    return False


async def finalize_post_shipping(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """ユーザーの二次確認後：確認チェック → 発送通知 → 「発送しました」を順にクリック。"""
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备发货确认…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    report("attach_browser", "正在连接已打开的浏览器…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    # ── Step 1: 確認チェックボックスにチェック（「ご依頼主様控えを切り取りました」等） ──
    report("check_confirm", "正在勾选确认项…")
    ticked = await _tick_ship_confirm_checkboxes(page)
    if ticked == 0:
        log.warning(
            "[postship] 確認チェックボックスが見つからず（当前 URL: %s）。"
            "そのまま発送通知ボタンを試行します。",
            page.url,
        )
    await asyncio.sleep(0.2)

    # ── Step 2: 「商品を発送したので、発送通知をする」 ──
    report("click_notify", "正在点击「発送通知をする」…")
    if not await _click_visible_button_by_text(page, _NOTIFY_SHIP_BUTTON_TEXT, timeout_ms=8000):
        raise RuntimeError(
            f"未找到/未能点击「{_NOTIFY_SHIP_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
        )
    log.info("[postship] 点击「%s」", _NOTIFY_SHIP_BUTTON_TEXT)

    # ── Step 3: 二次确认ダイアログ「発送しました」 ──
    # 通知ボタン押下後にモーダルが開く。アニメーション完了を待ってから、
    # 可視・有効なボタンだけをクリック（非表示の複製を踏まないように）
    report("click_shipped", "正在点击二次确认「発送しました」…")
    await asyncio.sleep(0.6)
    confirmed = await _click_visible_button_by_text(
        page, _SHIPPED_CONFIRM_BUTTON_TEXT, timeout_ms=8000,
    )
    if confirmed:
        log.info("[postship] 点击二次确认「%s」 完成发货通知", _SHIPPED_CONFIRM_BUTTON_TEXT)
    else:
        log.warning(
            "[postship] 二次确认「%s」按钮未出现/未能点击。URL: %s",
            _SHIPPED_CONFIRM_BUTTON_TEXT, page.url,
        )

    # ── Step 4: 数据発送＋页面再読込を待つ。「購入者の受取をお待ちください」が出れば成功 ──
    report("waiting_reload", "已发送，正在等待页面刷新与发送完成…")
    await asyncio.sleep(3)  # クリック後の送信・再読込待ち（要件）
    shipped_ok = False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if _SHIP_SUCCESS_TEXT in text:
            shipped_ok = True
            break
        await asyncio.sleep(0.5)
    if shipped_ok:
        log.info("[postship] 检测到「%s」 发送成功 todo=%s", _SHIP_SUCCESS_TEXT, todo_id)
    else:
        log.warning(
            "[postship] 未检测到「%s」(可能仍在处理)。URL: %s",
            _SHIP_SUCCESS_TEXT, page.url,
        )

    # ── Step 5: 成功确认后才软删除本地 todo（列表から消す） ──
    if shipped_ok:
        try:
            todo.is_delete = 1
            todo.synced_at = int(time.time() * 1000)
            todo.save()
            log.info("[postship] 已软删除 todo_id=%s", todo_id)
        except Exception as exc:
            log.warning("[postship] 软删除 todo 失败: %s", exc)

    report("done", "已完成发货通知" if shipped_ok else "已发送（未检测到完成文案）")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "success": bool(shipped_ok),
        "checkboxes_ticked": ticked,
        "shipped_confirmed": confirmed,
        "shipped_ok": shipped_ok,
    }


async def submit_transaction_review(
    todo_id: int,
    text: str,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在已打开的浏览器（取引評価页）填评价文本 + 点「購入者を評価して取引完了する」。

    页面上 ``良かった`` 通常默认选中，不需要再点。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备评价提交…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    body = (text or "").strip()
    if not body:
        raise ValueError("评价文本不能为空")

    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    report("attach_browser", "正在连接已打开的浏览器…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「处理」打开交易页") from exc

    # 找到评价 textarea（按 placeholder）
    report("fill_review", "正在填入评价文本…")
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
    report("click_submit", "正在点击「購入者を評価して取引完了する」…")
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
    report("confirm_dialog", "正在点击二次确认「取引を完了する」…")
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
    report("wait_completed", "等待煤炉返回「取引が完了しました」…")
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
        report("finalize", "评价完成，正在收尾并刷新订单…")
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
            await mgr.close_session(auto_key, force=True)
            log.info("[review] 已关闭主浏览器 account_id=%s", aid)
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

    report("done", "评价已提交")
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


# ====================================================================
# 取引メッセージのリアクション（emoji 反应）
# ====================================================================

# Mercari 取引メッセージの定型リアクション一覧
# Mercari picker 内 5 个 emoji 是按位置渲染的 ``<button><img/></button>``，没有 aria-label
# 也没有稳定的文本，只能按 ``button:nth-of-type(N)`` 定位。
# ``index`` 与煤炉 picker 的 1-based XPath（button[1]..button[5]）对应：
#   button[1] = 心  / button[2] = 微笑 / button[3] = 笑 / button[4] = 合掌 / button[5] = 祝
SUPPORTED_REACTIONS: Dict[str, Dict[str, Any]] = {
    "heart": {"emoji": "❤️", "index": 0, "label": "好き"},
    "smile": {"emoji": "😊", "index": 1, "label": "笑顔"},
    "laugh": {"emoji": "😆", "index": 2, "label": "笑い"},
    "pray": {"emoji": "🙏", "index": 3, "label": "ありがとう"},
    "party": {"emoji": "🎉", "index": 4, "label": "お祝い"},
}


async def send_message_reaction_by_index(
    todo_id: int,
    reaction_index: int,
    reaction: str,
    *,
    message_id: Optional[str] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """按「页面上第 reaction_index 个 add-reaction-button」定位并点击反应表情。

    前端调用时根据 ``messages.filter(is_buyer=true).indexOf(targetMessage)`` 计算 ``reaction_index``。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备发送反应表情…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    if reaction_index < 0:
        raise ValueError("reaction_index 不能小于 0")
    reaction_key = (reaction or "").strip().lower()
    if reaction_key not in SUPPORTED_REACTIONS:
        raise ValueError(f"reaction 取值非法：{reaction}（仅支持 {list(SUPPORTED_REACTIONS)}）")
    rinfo = SUPPORTED_REACTIONS[reaction_key]
    emoji_char = rinfo["emoji"]
    emoji_idx = int(rinfo["index"])

    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)

    report("attach_browser", "正在连接已打开的浏览器交易页…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「处理」打开交易页") from exc

    # ── Step 1: 找到第 reaction_index 个「add-reaction-button」并点击 ──
    # 注：``[data-testid="add-reaction-button"]`` 只在买家消息卡片下渲染，所以这个 N
    # 直接对应「买家消息中第 N 条」，无论页面上买家/卖家消息交错怎样排列都成立。
    report("click_add_reaction", "正在点击「+」反应按钮…")
    add_btns = page.locator('[data-testid="add-reaction-button"]')
    try:
        await add_btns.first.wait_for(state="visible", timeout=6000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到任何「+」反应按钮（可能该交易没有买家消息或页面未加载完；当前 URL: {page.url}）"
        ) from exc
    total = await add_btns.count()
    if reaction_index >= total:
        raise RuntimeError(
            f"reaction_index={reaction_index} 越界（页面共 {total} 个反应按钮）"
        )
    target_btn = add_btns.nth(reaction_index)
    try:
        await target_btn.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    await target_btn.click()
    log.info(
        "[reaction] 已点击 add-reaction-button index=%s account_id=%s todo_id=%s",
        reaction_index,
        aid,
        todo_id,
    )

    # ── Step 2: 在同一条消息卡片内定位 picker 的第 emoji_idx 个 emoji 按钮 ──
    # 煤炉的 picker 是 5 个 ``<button><img/></button>``，没有稳定 aria-label
    # 也没有可读文本，只能按位置取。这些 button 都嵌在 ``[data-testid="ds4-comment"]``
    # 卡片内部（XPath: .../div[3]/div/button[N]/img），因此用「卡片祖先 + 直接子级 img」过滤。
    report("pick_emoji", f"正在选择 emoji（{emoji_char}）…")
    await asyncio.sleep(0.3)
    parent_comment = target_btn.locator('xpath=ancestor::*[@data-testid="ds4-comment"][1]')
    # ``button:has(> img)`` 排除掉 add-reaction-button（其子节点是 svg 不是 img）
    # 也排除掉头像（头像是 <a> + <picture><img>，不是 <button>）
    emoji_btns = parent_comment.locator('button:has(> img)')
    try:
        await emoji_btns.first.wait_for(state="visible", timeout=4000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到 emoji picker 按钮（点击「+」后弹出层未出现；当前 URL: {page.url}）"
        ) from exc

    total_emojis = await emoji_btns.count()
    if total_emojis < len(SUPPORTED_REACTIONS):
        log.warning(
            "[reaction] picker emoji 数量不匹配（页面 %s 个 / 预期 %s 个）",
            total_emojis,
            len(SUPPORTED_REACTIONS),
        )
    if emoji_idx >= total_emojis:
        raise RuntimeError(
            f"emoji 索引 {emoji_idx} 越界（picker 共 {total_emojis} 个 emoji）"
        )

    await emoji_btns.nth(emoji_idx).click()
    log.info(
        "[reaction] 已点击 emoji=%s key=%s index=%s account_id=%s",
        emoji_char,
        reaction_key,
        emoji_idx,
        aid,
    )
    await asyncio.sleep(0.5)

    report("done", "反应表情已发送")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "reaction_index": reaction_index,
        "reaction": reaction_key,
        "emoji": emoji_char,
        "emoji_index": emoji_idx,
        "message_id": message_id,
        "sent": True,
    }


async def _click_change_method_entry(page: Any, *, timeout_ms: int = 8000) -> bool:
    """点击交易页的「発送方法を変更する」入口。

    この要素は ``<a data-location="...change_shipping_method_button">`` という
    リンク（role=link）であり ``<button>`` ではない。data-location を最優先に、
    link/button/テキストへ順に回落しつつ、可視要素のみをクリックする。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        candidates = [
            page.locator('[data-location*="change_shipping_method_button"]'),
            page.get_by_role("link", name=_CHANGE_METHOD_BUTTON_TEXT),
            page.get_by_role("button", name=_CHANGE_METHOD_BUTTON_TEXT),
            page.locator(f'a:has-text("{_CHANGE_METHOD_BUTTON_TEXT}")'),
            page.locator(f'button:has-text("{_CHANGE_METHOD_BUTTON_TEXT}")'),
        ]
        for loc in candidates:
            try:
                n = await loc.count()
            except Exception:
                n = 0
            for i in range(n):
                el = loc.nth(i)
                try:
                    if await el.is_visible():
                        await el.scroll_into_view_if_needed(timeout=1500)
                        await el.click()
                        return True
                except Exception:
                    continue
        await asyncio.sleep(0.3)
    return False


async def click_change_shipping_method(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「発送方法を変更する」（导航到修改发送方式页；后续由用户在浏览器内手动）。"""
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"

    # 点「处理」不再自动开浏览器，因此本操作需自行确保浏览器已打开并停在交易页。
    is_wait_shipping = _is_wait_shipping_todo(todo)
    headless_override = False if is_wait_shipping else None
    minimized_override = False if is_wait_shipping else None
    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=headless_override,
        minimized=minimized_override,
    ) as (mgr, auto_key):
        page = await mgr.active_tab_page(auto_key)

        report("locate_button", "正在定位「発送方法を変更する」…")
        # 注意：交易页的「発送方法を変更する」是 <a> 链接（role=link），不是 <button>。
        # 因此 get_by_role("button") / button:has-text 都匹配不到。优先用稳定的 data-location，
        # 再回落到 link/button/任意可点元素的文本匹配，并做可视+轮询。
        if not await _click_change_method_entry(page):
            raise RuntimeError(
                f"未找到「{_CHANGE_METHOD_BUTTON_TEXT}」入口（当前 URL: {page.url}）"
            )
        report("click_button", "正在点击「発送方法を変更する」…")
        log.info("[shipping] 已点击「%s」 account_id=%s", _CHANGE_METHOD_BUTTON_TEXT, aid)

        # 等待跳转到 /shipping_method 并抓取可选配送方式（radio）
        try:
            await page.wait_for_url("**/shipping_method*", timeout=8000)
        except Exception:
            log.warning("[shipping] /shipping_method への遷移を観測できず (URL: %s)", page.url)
        await asyncio.sleep(0.4)
        options = await _scrape_shipping_method_options(page)
    report("done", "已跳转修改发送方式页")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "clicked": True,
        "options": options,
    }


# 已发行二维码后修改发货方式：交易页上的「商品サイズや発送方法を修正する」按钮
_REVISE_SLIP_BUTTON_TEXT = "商品サイズや発送方法を修正する"
_REVISE_SLIP_BUTTON_LOCATION = "transaction:publish:change_shipping_button"


async def _click_dialog_change_confirm(page: Any) -> bool:
    """点二次确认弹窗的行动按钮：优先 data-testid，回落 dialog 内「変更する/修正する」文本。"""
    try:
        b = page.locator('[data-testid="dialog-action-button"]')
        await b.first.wait_for(state="visible", timeout=5000)
        await b.first.click()
        return True
    except Exception:
        pass
    for text in (_CHANGE_METHOD_SUBMIT_TEXT, "修正する"):
        try:
            b = page.locator(f'[role="dialog"] button:has-text("{text}")')
            if await b.count() > 0 and await b.first.is_visible():
                await b.first.click()
                return True
        except Exception:
            pass
    return False


async def revise_shipping_after_qr(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """已发行二维码后修改发货方式：点「商品サイズや発送方法を修正する」→ 二次确认「変更する」
    → 清除已保存的二维码，恢复到可重新选择尺寸/发货方式的状态。"""
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"

    is_wait_shipping = _is_wait_shipping_todo(todo)
    headless_override = False if is_wait_shipping else None
    minimized_override = False if is_wait_shipping else None
    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=headless_override,
        minimized=minimized_override,
    ) as (mgr, auto_key):
        page = await mgr.active_tab_page(auto_key)

        report("locate_revise", "正在定位「商品サイズや発送方法を修正する」…")
        clicked = False
        loc = page.locator(f'[data-location="{_REVISE_SLIP_BUTTON_LOCATION}"] button')
        try:
            await loc.first.wait_for(state="visible", timeout=8000)
            await loc.first.click()
            clicked = True
        except Exception:
            btn = page.get_by_role("button", name=_REVISE_SLIP_BUTTON_TEXT)
            try:
                await btn.first.wait_for(state="visible", timeout=4000)
                await btn.first.click()
                clicked = True
            except Exception:
                btn2 = page.locator(f'button:has-text("{_REVISE_SLIP_BUTTON_TEXT}")')
                try:
                    if await btn2.count() > 0 and await btn2.first.is_visible():
                        await btn2.first.click()
                        clicked = True
                except Exception:
                    pass
        if not clicked:
            raise RuntimeError(
                f"未找到「{_REVISE_SLIP_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            )
        log.info("[shipping] 已点击「%s」 account_id=%s", _REVISE_SLIP_BUTTON_TEXT, aid)

        # 二次确认弹窗 → 点「変更する」
        report("confirm_revise", "正在确认「変更する」…")
        await asyncio.sleep(0.4)
        if not await _click_dialog_change_confirm(page):
            log.warning("[shipping] 二次确认「変更する」未出现或已自动提交 (URL: %s)", page.url)
        # 等回到交易页（修正后回到可重新选择尺寸/方式的状态）
        try:
            await page.wait_for_url("**/transaction/*", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.6)

    # 清除已保存的二维码（DB + 本地文件 + detail_json）
    _clear_qr_image(int(todo_id))
    report("done", "已修正发货方式并清除二维码")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "clicked": True,
        "qr_image_url": None,
    }


async def _scrape_shipping_method_options(page: Any) -> List[Dict[str, Any]]:
    """抓取 /shipping_method 页配送方式 radio 选项（label / value / 是否已选中）。"""
    try:
        opts = await page.evaluate(
            """(name) => {
                const radios = Array.from(document.querySelectorAll('input[name="' + name + '"]'));
                return radios.map((r) => {
                    let label = r.getAttribute('aria-label') || '';
                    if (!label) {
                        const lc = r.closest('label');
                        if (lc) label = (lc.textContent || '').trim();
                    }
                    return {
                        value: r.getAttribute('value') || '',
                        label: label,
                        data_location: r.getAttribute('data-location') || '',
                        checked: r.getAttribute('aria-checked') === 'true' || r.checked === true,
                    };
                });
            }""",
            _CHANGE_METHOD_RADIO_NAME,
        )
        return [o for o in (opts or []) if (o or {}).get("label")]
    except Exception as exc:
        log.debug("[change-method] 配送方式の取得に失敗: %s", exc)
        return []


async def confirm_change_shipping_method(
    todo_id: int,
    method_value: str = "",
    *,
    method_label: str = "",
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在 /shipping_method 页选中指定配送方式（按 value 优先，回落 aria-label/文本）并点「変更する」。"""
    report = make_sync_reporter(progress_job_id)
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_account_key(aid)
    report("attach_browser", "正在连接已打开的浏览器…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭，请先点「処理」打开交易页") from exc

    val = str(method_value or "").strip()
    lbl = str(method_label or "").strip()

    report("select_method", "正在选择配送方式…")
    selected = False
    if val:
        try:
            loc = page.locator(
                f'input[name="{_CHANGE_METHOD_RADIO_NAME}"][value="{val}"]'
            )
            if await loc.count() > 0:
                await loc.first.check(force=True)
                selected = True
        except Exception as exc:
            log.debug("[change-method] value 选中失败: %s", exc)
    if not selected and lbl:
        try:
            loc = page.locator(
                f'input[name="{_CHANGE_METHOD_RADIO_NAME}"][aria-label="{lbl}"]'
            )
            if await loc.count() > 0:
                await loc.first.check(force=True)
                selected = True
        except Exception as exc:
            log.debug("[change-method] aria-label 选中失败: %s", exc)
    if not selected and lbl:
        try:
            await page.get_by_text(lbl, exact=False).first.click()
            selected = True
        except Exception as exc:
            log.debug("[change-method] 文本点击失败: %s", exc)
    if not selected:
        raise RuntimeError("未找到对应的配送方式选项")

    await asyncio.sleep(0.3)
    report("click_submit", "正在点击「変更する」…")
    clicked = False
    submit = page.get_by_role("button", name=_CHANGE_METHOD_SUBMIT_TEXT)
    try:
        if (
            await submit.count() > 0
            and await submit.first.is_visible()
            and await submit.first.is_enabled()
        ):
            await submit.first.click()
            clicked = True
    except Exception as exc:
        log.debug("[change-method] role 按钮点击失败: %s", exc)
    if not clicked:
        sub2 = page.locator(f'button:has-text("{_CHANGE_METHOD_SUBMIT_TEXT}")')
        try:
            await sub2.first.wait_for(state="visible", timeout=3000)
            await sub2.first.click()
            clicked = True
        except Exception as exc:
            raise RuntimeError(f"未找到「{_CHANGE_METHOD_SUBMIT_TEXT}」按钮") from exc

    # 二次确认弹窗：点击第一次「変更する」后会弹出确认 dialog，里面还有一个「変更する」
    # （data-testid="dialog-action-button"），需要再点一次才会真正提交。
    report("confirm_submit", "正在确认「変更する」…")
    try:
        confirm_btn = page.locator('[data-testid="dialog-action-button"]')
        await confirm_btn.first.wait_for(state="visible", timeout=4000)
        await confirm_btn.first.click()
        log.info("[shipping] 已点击二次确认「%s」 account_id=%s", _CHANGE_METHOD_SUBMIT_TEXT, aid)
    except Exception:
        # 回落：在 dialog/footer 区域里按文本找第二个「変更する」
        try:
            dlg_submit = page.locator(
                f'[role="dialog"] button:has-text("{_CHANGE_METHOD_SUBMIT_TEXT}")'
            )
            if await dlg_submit.count() > 0 and await dlg_submit.first.is_visible():
                await dlg_submit.first.click()
                log.info("[shipping] 已点击二次确认（回落） account_id=%s", aid)
        except Exception as exc:
            log.debug("[change-method] 二次确认未出现或已自动提交: %s", exc)

    # 等待回到 transaction 详情页（离开 /shipping_method）
    try:
        await page.wait_for_url("**/transaction/*", timeout=8000)
    except Exception:
        log.warning("[shipping] 変更後 transaction への遷移を観測できず (URL: %s)", page.url)
    log.info("[shipping] 已变更配送方式 value=%s label=%s account_id=%s", val, lbl, aid)
    report("done", "配送方式已变更")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "success": True,
        "method_value": val,
        "method_label": lbl,
    }
