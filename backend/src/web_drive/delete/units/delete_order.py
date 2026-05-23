# -*- coding: utf-8 -*-
"""
Mercari 在售商品删除：MITM 有头最小化 Edge 打开编辑页并删除，完成后同步列表并关闭浏览器。

流程：
  1. 在 ``meilu_{id}__auto`` profile 上启动有头最小化 Edge（Cookie 从 ``meilu_{id}`` 磁盘 seed）
  2. 点击「この商品を削除する」→ 弹窗内点击「削除する」
  3. 等待跳转出品一覧，MITM 截获 items/get_items 并同步本地
  4. 自动 close_session 关闭浏览器
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ...listing.units.post_to_macket import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    _click_by_texts,
)

log = logging.getLogger(__name__)

SELL_EDIT_URL_TPL = "https://jp.mercari.com/sell/edit/{item_seg}"

DELETE_ENTRY_TEXT = "この商品を削除する"
DELETE_CONFIRM_TEXT = "削除する"
DELETE_DIALOG_TESTID = "deletion-dialog"
DELETE_DIALOG_ACTION_TESTID = "dialog-action-button"
DELETE_DIALOG_TITLE_TEXT = "この商品を削除しますか？"


def mercari_item_path_segment(item_id: str) -> str:
    """煤炉商品路径段：API 多为 m 开头，纯数字时补 m。"""
    raw = (item_id or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("m") else f"m{raw}"


def build_sell_edit_url(item_id: str) -> str:
    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")
    return SELL_EDIT_URL_TPL.format(item_seg=seg)


async def _page_for_session(manager: Any, session_key: str) -> Any:
    s = manager._prepare_async()
    async with s.lock:  # type: ignore[union-attr]
        ctx = s.contexts.get(session_key)
        if ctx is None or not manager._is_context_alive(ctx):
            raise RuntimeError(f"会话启动失败: {session_key}")
        return ctx.pages[-1] if ctx.pages else await ctx.new_page()


async def _click_delete_confirm_in_dialog(
    page: Any,
    *,
    element_timeout_ms: int,
) -> None:
    """
    在二次确认弹窗（data-testid=deletion-dialog）内点击「削除する」。
    优先 [data-testid=dialog-action-button] button，再按弹窗内文案兜底。
    """
    dialog = page.locator(f'[data-testid="{DELETE_DIALOG_TESTID}"]')
    await dialog.wait_for(state="visible", timeout=element_timeout_ms)

    try:
        title_loc = dialog.get_by_text(DELETE_DIALOG_TITLE_TEXT, exact=False).first
        await title_loc.wait_for(state="visible", timeout=element_timeout_ms)
    except Exception:
        log.info("[delete_mercari_item] 未检测到弹窗标题，继续尝试点击确认按钮")

    last_exc: Optional[BaseException] = None
    for factory in (
        lambda: dialog.locator(
            f'[data-testid="{DELETE_DIALOG_ACTION_TESTID}"] button'
        ).first,
        lambda: dialog.get_by_role("button", name=DELETE_CONFIRM_TEXT),
        lambda: dialog.locator(f'button:has-text("{DELETE_CONFIRM_TEXT}")'),
    ):
        try:
            loc = factory()
            await loc.wait_for(state="visible", timeout=element_timeout_ms)
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=element_timeout_ms)
            log.info(
                "[delete_mercari_item] 已在 deletion-dialog 内点击「%s」",
                DELETE_CONFIRM_TEXT,
            )
            return
        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc if last_exc else RuntimeError(
        f"未在删除确认弹窗内找到「{DELETE_CONFIRM_TEXT}」按钮"
    )


async def delete_mercari_item(
    manager: Any,
    account_key: str,
    *,
    item_id: str,
    proxy_server: Optional[str] = None,  # noqa: ARG001 — MITM 由 mitm_automation_browser 统一配置
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """
    使用 MITM 浏览器（``meilu_{id}__auto`` 有头最小化）删除商品并同步在售列表；结束后自动关闭浏览器。
    """
    from ...core.manager import EdgeWebDriveManager
    from ...core.mitm_session import mitm_automation_browser
    from ...core.paths import meilu_automation_key, meilu_id_from_account_key
    from ....use_mercari.get_order.get_on_sale.on_sale_list import (
        LISTINGS_PAGE_URL,
        sync_on_sale_from_listings_browser_page,
    )
    from ....use_mercari.sync_data import _resolve_account_and_seller
    from ....ssl_mitm_proxy.capture_config import clear_on_sale_list_response_file

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")

    account_id = meilu_id_from_account_key(account_key)
    if account_id is None:
        raise ValueError(f"无效的 account_key: {account_key}")

    _aid, seller_id = _resolve_account_and_seller(account_id)
    seller_key = str(int(seller_id))
    auto_key = meilu_automation_key(account_id)
    edit_url = build_sell_edit_url(item_id)

    clear_on_sale_list_response_file(seller_key)

    log.info(
        "[delete_mercari_item] account=%s auto=%s item=%s url=%s",
        account_key,
        auto_key,
        seg,
        edit_url,
    )

    result: Dict[str, Any] = {
        "account_key": account_key,
        "browser_key": auto_key,
        "item_id": seg,
        "edit_url": edit_url,
        "url_before_delete": None,
        "delete_entry_clicked": False,
        "delete_confirmed": False,
        "url_after_delete": None,
        "listings_url": LISTINGS_PAGE_URL,
        "sync": None,
        "browser_closed": False,
    }

    async with mitm_automation_browser(
        account_id,
        start_url=edit_url,
    ) as (mgr, browser_key):
        page = await _page_for_session(mgr, browser_key)

        try:
            await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
        except Exception:
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=page_load_timeout_ms
                )
            except Exception:
                pass

        result["url_before_delete"] = page.url

        await _click_by_texts(
            page,
            (DELETE_ENTRY_TEXT,),
            element_timeout_ms=element_timeout_ms,
            log_prefix="[delete_mercari_item]",
        )
        result["delete_entry_clicked"] = True

        capture_since_ms = int(time.time() * 1000)
        await _click_delete_confirm_in_dialog(
            page,
            element_timeout_ms=element_timeout_ms,
        )
        result["delete_confirmed"] = True

        try:
            await page.locator(f'[data-testid="{DELETE_DIALOG_TESTID}"]').wait_for(
                state="hidden",
                timeout=element_timeout_ms,
            )
        except Exception:
            pass

        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=page_load_timeout_ms
            )
        except Exception:
            pass

        result["url_after_delete"] = page.url
        log.info(
            "[delete_mercari_item] 删除已确认，等待出品一覧并同步 account=%s item=%s",
            account_key,
            seg,
        )

        sync_stats = await sync_on_sale_from_listings_browser_page(
            mgr,
            browser_key,
            int(seller_id),
            page,
            capture_since_ms=capture_since_ms,
            timeout=max(90, element_timeout_ms // 1000),
        )
        result["sync"] = sync_stats
        result["url_after_delete"] = page.url

    result["browser_closed"] = True
    log.info(
        "[delete_mercari_item] 完成并已关闭浏览器 account=%s item=%s marked_deleted=%s",
        account_key,
        seg,
        (result.get("sync") or {}).get("marked_deleted"),
    )
    return result
