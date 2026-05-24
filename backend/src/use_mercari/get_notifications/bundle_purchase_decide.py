# -*- coding: utf-8 -*-
"""
合并购买请求承诺 / 拒绝（依頼を承諾する / 依頼を断る）。

- 使用账号主 profile 持久化浏览器（``meilu_{id}``，经 MITM 代理），不走串行队列；
- 进入 ``/bundle_offer/{bundle_id}`` 后：
    accept → 按 XPath 填写 4 个 select → 按文本点「依頼を承諾する」
    reject → 直接按文本点「依頼を断る」
- 完成后立即关闭浏览器（不依赖队列空闲关闭）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from ...db_manage.models.meilu_account import MeiluAccountModel
from ...web_drive.core.manager import EdgeWebDriveManager
from ...web_drive.core.mitm_session import mitm_automation_browser
from ...web_drive.core.paths import meilu_account_key
from .bundle_purchase_capture import build_bundle_offer_url

log = logging.getLogger(__name__)

# ───────── /bundle_offer/{id} 表单 XPath（用户提供） ─────────

SHIPPING_PAYER_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[1]/div/label/div/select"
)
SHIPPING_METHOD_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[2]/div/label/div/select"
)
SHIPPING_FROM_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[3]/div/label/div/select"
)
SHIPPING_DAYS_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[4]/div/label/div/select"
)

# Playwright select_option 的 index 为 0-based
SHIPPING_PAYER_OPTION_INDEX: Dict[str, int] = {
    "seller": 0,  # 第一个：包邮（送料込み）
    "buyer": 1,  # 第二个：到付（着払い）
}

# 顺序与 /bundle_offer/{id} 页下拉框一致（参考图 2）
SHIPPING_METHOD_OPTION_INDEX: Dict[str, int] = {
    "undecided": 0,
    "rakuraku": 1,
    "yuuyu": 2,
    "takunomeru": 3,
    "yumail": 4,
    "letter_pack": 5,
    "postal": 6,
    "kuroneko": 7,
    "yupack": 8,
    "clickpost": 9,
    "yupacket": 10,
}

SHIPPING_DAYS_OPTION_INDEX: Dict[str, int] = {
    "1_2_days": 0,
    "2_3_days": 1,
    "4_7_days": 2,
}

ACCEPT_BUTTON_TEXT = "依頼を承諾する"
REJECT_BUTTON_TEXT = "依頼を断る"

ELEMENT_TIMEOUT_MS = 15_000
PAGE_NAV_TIMEOUT_MS = 30_000


async def _react_set_select(page: Any, xpath: str, value: str) -> bool:
    """通过原生 setter + change 事件写入 select 值（兜底 React 受控组件）。"""
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [xpath, value],
    )


async def _select_by_index(
    page: Any, xpath: str, index: int, *, label: str
) -> None:
    """按 0-based index 选择 select option；失败时兜底 JS 写入 option.value。"""
    select_loc = page.locator(f"xpath={xpath}")
    await select_loc.first.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
    await select_loc.first.scroll_into_view_if_needed()
    try:
        await select_loc.first.select_option(index=index, timeout=ELEMENT_TIMEOUT_MS)
        log.info("[bundle_decide] %s 已选 index=%d", label, index)
        return
    except Exception as exc:
        log.warning("[bundle_decide] %s select_option(index) 失败,改用JS: %s", label, exc)

    # 兜底：用 JS 读出对应 option 的 value 再写入
    opt_xpath = f"{xpath}/option[{index + 1}]"
    opt_value = await page.evaluate(
        """(xpath) => {
            const el = document.evaluate(xpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            return el ? el.value : null;
        }""",
        opt_xpath,
    )
    if opt_value is None:
        raise RuntimeError(f"{label} option[{index + 1}] 不存在")
    ok = await _react_set_select(page, xpath, str(opt_value))
    if not ok:
        raise RuntimeError(f"{label} JS 设置 option value={opt_value} 失败")
    log.info("[bundle_decide] %s JS设置 option value=%s", label, opt_value)


async def _select_shipping_from(page: Any, area_id: str) -> None:
    aid = str(area_id or "").strip()
    if not aid:
        raise ValueError("shipping_from(area_id) 不能为空")
    select_loc = page.locator(f"xpath={SHIPPING_FROM_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
    await select_loc.first.scroll_into_view_if_needed()
    try:
        await select_loc.first.select_option(value=aid, timeout=ELEMENT_TIMEOUT_MS)
        log.info("[bundle_decide] shipping_from 已选 area_id=%s", aid)
        return
    except Exception as exc:
        log.warning("[bundle_decide] shipping_from select_option(value) 失败,改用JS: %s", exc)
    ok = await _react_set_select(page, SHIPPING_FROM_SELECT_XPATH, aid)
    if not ok:
        raise RuntimeError(f"shipping_from JS 设置 area_id={aid} 失败")


async def _fill_offer_form(
    page: Any,
    *,
    shipping_payer: str,
    shipping_method: str,
    shipping_from: str,
    shipping_days: str,
) -> None:
    payer_idx = SHIPPING_PAYER_OPTION_INDEX.get((shipping_payer or "").strip())
    if payer_idx is None:
        raise ValueError(f"非法 shipping_payer: {shipping_payer!r}")
    method_idx = SHIPPING_METHOD_OPTION_INDEX.get((shipping_method or "").strip())
    if method_idx is None:
        raise ValueError(f"非法 shipping_method: {shipping_method!r}")
    days_idx = SHIPPING_DAYS_OPTION_INDEX.get((shipping_days or "").strip())
    if days_idx is None:
        raise ValueError(f"非法 shipping_days: {shipping_days!r}")

    await _select_by_index(
        page, SHIPPING_PAYER_SELECT_XPATH, payer_idx, label="shipping_payer"
    )
    await _select_by_index(
        page, SHIPPING_METHOD_SELECT_XPATH, method_idx, label="shipping_method"
    )
    await _select_shipping_from(page, shipping_from)
    await _select_by_index(
        page, SHIPPING_DAYS_SELECT_XPATH, days_idx, label="shipping_days"
    )


async def _click_button_by_text(page: Any, text: str) -> None:
    """文本定位 + 点击。优先按 role=button + 精确文本,兜底 :has-text。"""
    candidates = [
        page.get_by_role("button", name=text, exact=True),
        page.locator(f"button:has-text('{text}')"),
        page.locator(f"text={text}"),
    ]
    last_exc: Optional[BaseException] = None
    for loc in candidates:
        try:
            await loc.first.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
            await loc.first.scroll_into_view_if_needed()
            await loc.first.click(timeout=ELEMENT_TIMEOUT_MS)
            log.info("[bundle_decide] 已点击按钮: %s", text)
            return
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"未找到可点击的按钮文本: {text}: {last_exc}")


def _resolve_account_id(account_id: Optional[int]) -> int:
    if account_id is not None:
        acc = MeiluAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            raise ValueError(f"煤炉账号 id={account_id} 不存在")
        return int(account_id)
    rows = MeiluAccountModel.find_all(
        where="[status] = ? AND [is_open] = 1",
        params=("active",),
        order_by="[id] ASC",
        limit=1,
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active 且 is_open=1）")
    return int(rows[0].id)


async def _close_browser_safely(mgr: EdgeWebDriveManager, main_key: str) -> None:
    try:
        await mgr.close_session(main_key, force=True)
    except Exception as exc:
        log.warning("[bundle_decide] 关闭浏览器失败 key=%s: %s", main_key, exc)


async def decide_bundle_purchase(
    *,
    bundle_id: str,
    account_id: Optional[int] = None,
    action: str,
    shipping_payer: Optional[str] = None,
    shipping_method: Optional[str] = None,
    shipping_from: Optional[str] = None,
    shipping_days: Optional[str] = None,
) -> Dict[str, Any]:
    """
    打开 /bundle_offer/{bundle_id}（持久化主 profile + MITM），
    accept 填表 + 点「依頼を承諾する」；reject 直接点「依頼を断る」。
    完成后关闭浏览器。**不使用队列**。
    """
    bid = str(bundle_id or "").strip()
    if not bid:
        raise ValueError("bundle_id 不能为空")
    act = (action or "").strip().lower()
    if act not in ("accept", "reject"):
        raise ValueError(f"非法 action: {action!r}")

    aid = _resolve_account_id(account_id)
    main_key = meilu_account_key(int(aid))
    start_url = build_bundle_offer_url(bid)

    log.info(
        "[bundle_decide] start account_id=%s bundle_id=%s action=%s", aid, bid, act
    )

    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, key):
        # mitm_automation_browser 复用现有会话或重新打开;此处直接拿 active page
        page = await mgr.active_tab_page(key)

        # 确认 URL 进入了 bundle_offer 页;若没有则显式 goto 一次
        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        if "/bundle_offer/" not in cur_url:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS)

        try:
            if act == "accept":
                await _fill_offer_form(
                    page,
                    shipping_payer=shipping_payer or "",
                    shipping_method=shipping_method or "",
                    shipping_from=shipping_from or "",
                    shipping_days=shipping_days or "",
                )
                # 给 React 一点稳定时间再点击
                await asyncio.sleep(0.4)
                await _click_button_by_text(page, ACCEPT_BUTTON_TEXT)
            else:
                await _click_button_by_text(page, REJECT_BUTTON_TEXT)

            # 等点击后的导航 / 状态切换稍作稳定
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
                )
            except Exception:
                pass
            await asyncio.sleep(0.6)
        finally:
            await _close_browser_safely(mgr, key)

    log.info(
        "[bundle_decide] done account_id=%s bundle_id=%s action=%s", aid, bid, act
    )
    return {
        "account_id": int(aid),
        "bundle_id": bid,
        "action": act,
        "clicked": ACCEPT_BUTTON_TEXT if act == "accept" else REJECT_BUTTON_TEXT,
    }
