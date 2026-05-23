# -*- coding: utf-8 -*-
"""
Mercari 在售商品列表：通过账号对应 WebDriver 打开
``https://jp.mercari.com/mypage/listings``（经 SSL 中间人代理），
由 mitmproxy 截获 ``GET https://api.mercari.jp/items/get_items``（status 含 on_sale/stop）
的响应体，不再直接 HTTP 调用 API。

页面需先滚至底部才会出现「もっと見る」；存在时会自动循环点击并合并各次截获的分页数据，
直至 ``meta.total_item_count`` 已全部合并或 ``has_next`` 为 false 且按钮消失。
「从煤炉同步」完成后可在**同一浏览器会话**内对本次新增商品自动执行与「获取详情」相同的逻辑（见 ``on_sale_item_detail_sync.auto_fetch_details_for_inserted_items``）。

MITM 浏览器使用独立 profile：``meilu_{account_id}__auto``（与账号页有头 ``meilu_{account_id}`` 分离）。
每次操作启动一个独立的有头最小化 Edge 进程，截获完成后会在 ``finally`` 中关闭该浏览器会话。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from ....ssl_mitm_proxy.capture_config import (
    clear_on_sale_list_response_file,
    read_on_sale_list_response,
)
from ....ssl_mitm_proxy.runner import start_mitm_proxy
from ....web_drive.core.manager import EdgeWebDriveManager
from ....web_drive.core.mitm_session import mitm_automation_browser, wait_mitm_capture

log = logging.getLogger(__name__)

_API_BASE = "https://api.mercari.jp/items/get_items"
LISTINGS_PAGE_URL = "https://jp.mercari.com/mypage/listings"
LISTINGS_URL_FRAGMENT = "mypage/listings"
LISTINGS_REDIRECT_TIMEOUT_MS = 60_000
LISTINGS_LOAD_MORE_TEXT = "もっと見る"
LISTINGS_PAGE_BATCH_SIZE = 30
LISTINGS_NEED_PAGINATION_TOTAL_THRESHOLD = 50
_LISTINGS_LOAD_MORE_MAX_ROUNDS = 500
_LISTINGS_AFTER_CLICK_CAPTURE_WAIT_SEC = 45.0
_LISTINGS_SCROLL_STEPS = 10
_LISTINGS_SCROLL_PAUSE_SEC = 0.28


def build_on_sale_list_url(seller_id: int) -> str:
    """
    与页面触发的查询参数一致（seller_id 可变，其余固定），便于对照抓包。
    """
    params = {
        "order_by": "desc",
        "seller_id": str(int(seller_id)),
        "sort_type": "updated",
        "status": "on_sale,stop",
        "with_action_hints": "false",
        "with_auction": "true",
        "with_enhanced_hints": "true",
        "with_impression_boost": "true",
        "with_total_item_count": "false",
    }
    return f"{_API_BASE}?{urlencode(params)}"


def _parse_on_sale_list_capture(seller_key: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    wrapped = read_on_sale_list_response(seller_key) or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"截获数据格式异常: {wrapped!r}")
    if body.get("result") != "OK":
        raise RuntimeError(f"API 返回异常: {body}")
    items: List[Dict[str, Any]] = body.get("data") or []
    meta: Dict[str, Any] = body.get("meta") or {}
    return items, meta


def _merge_on_sale_items_by_id(chunk: List[Dict[str, Any]], into: Dict[str, Dict[str, Any]]) -> None:
    """按煤炉商品 id 合并分页结果（后者覆盖同 id）。"""
    for it in chunk:
        iid = str(it.get("id") or "").strip()
        if iid:
            into[iid] = it


def _meta_total_item_count(meta: Dict[str, Any]) -> int:
    try:
        return max(0, int(meta.get("total_item_count") or 0))
    except (TypeError, ValueError):
        return 0


def _needs_more_on_sale_list_pages(meta: Dict[str, Any], merged_count: int) -> bool:
    """
    是否仍需翻页：以 ``total_item_count`` 为准（>50 时通常需多次 limit=30 请求），
    辅以 ``has_next``；总数未知时仅看 has_next。
    """
    total = _meta_total_item_count(meta)
    if total > 0 and merged_count < total:
        return True
    if meta.get("has_next") is True:
        return True
    if (
        total == 0
        and merged_count >= LISTINGS_NEED_PAGINATION_TOTAL_THRESHOLD
        and merged_count % LISTINGS_PAGE_BATCH_SIZE == 0
    ):
        # 响应未带 total_item_count 时，已满一页（30）且数量≥50 则继续尝试翻页
        return True
    return False


async def _scroll_listings_page_to_bottom(page: Any) -> None:
    """出品一覧须滚到页面最底，「もっと見る」才会出现在 DOM 中。"""
    scroll_js = """
(el) => {
  if (!el) return;
  const h = el.scrollHeight || 0;
  el.scrollTop = h;
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: h, behavior: 'instant' });
  }
}
"""
    for selector in ("#main", "main", "[role='main']"):
        try:
            loc = page.locator(selector).first
            if await loc.count() == 0:
                continue
            for _ in range(_LISTINGS_SCROLL_STEPS):
                await loc.evaluate(scroll_js)
                await asyncio.sleep(_LISTINGS_SCROLL_PAUSE_SEC)
            break
        except Exception:
            continue
    try:
        await page.evaluate(
            "() => window.scrollTo(0, Math.max("
            "document.body.scrollHeight, document.documentElement.scrollHeight))"
        )
    except Exception:
        pass
    await asyncio.sleep(0.35)


async def _wait_new_on_sale_file_capture(
    seller_key: str,
    *,
    min_ts: int,
    wait_seconds: float,
) -> Optional[Dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        wrapped = read_on_sale_list_response(seller_key)
        if wrapped and int(wrapped.get("ts") or 0) > min_ts:
            return wrapped
        await asyncio.sleep(0.35)
    return None


async def _click_listings_load_more_if_present(
    page: Any,
    *,
    scroll_first: bool = True,
) -> bool:
    """出品一覧页滚到底后，若存在「もっと見る」则点击一次。"""
    if scroll_first:
        await _scroll_listings_page_to_bottom(page)

    timeout_ms = 3500
    click_timeout_ms = 10_000
    label = LISTINGS_LOAD_MORE_TEXT
    factories = (
        lambda: page.get_by_role("button", name=label),
        lambda: page.get_by_role("link", name=label),
        lambda: page.locator("#main").get_by_text(label, exact=True),
        lambda: page.get_by_text(label, exact=True),
    )
    for factory in factories:
        try:
            loc = factory().first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            await loc.scroll_into_view_if_needed(timeout=timeout_ms)
            await loc.click(timeout=click_timeout_ms)
            return True
        except Exception:
            continue
    return False


async def _expand_on_sale_listings_until_end(
    page: Any,
    seller_key: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    先滚至页面底部，循环点击「もっと見る」并等待 MITM 截获 ``items/get_items``
    （含 ``max_pager_id`` 的后续页，每次约 30 条）。MITM 每次覆盖同一响应文件，
    故对各次响应的 ``data`` 按 ``id`` 合并，直至条数达到 ``meta.total_item_count``
    或无需再翻页。
    """
    items, meta = _parse_on_sale_list_capture(seller_key)
    merged: Dict[str, Dict[str, Any]] = {}
    _merge_on_sale_items_by_id(items, merged)

    wrapped = read_on_sale_list_response(seller_key) or {}
    last_ts = int(wrapped.get("ts") or 0)

    await _scroll_listings_page_to_bottom(page)

    for round_idx in range(_LISTINGS_LOAD_MORE_MAX_ROUNDS):
        if not _needs_more_on_sale_list_pages(meta, len(merged)):
            break

        clicked = await _click_listings_load_more_if_present(page, scroll_first=True)
        if not clicked:
            await _scroll_listings_page_to_bottom(page)
            await asyncio.sleep(0.45)
            clicked = await _click_listings_load_more_if_present(page, scroll_first=False)
        if not clicked:
            if _needs_more_on_sale_list_pages(meta, len(merged)):
                log.warning(
                    "在售一覧仍需翻页但未找到「%s」round=%s merged=%s total=%s has_next=%s seller_id=%s",
                    LISTINGS_LOAD_MORE_TEXT,
                    round_idx,
                    len(merged),
                    _meta_total_item_count(meta),
                    meta.get("has_next"),
                    seller_key,
                )
            break

        new_wrapped = await _wait_new_on_sale_file_capture(
            seller_key,
            min_ts=last_ts,
            wait_seconds=_LISTINGS_AFTER_CLICK_CAPTURE_WAIT_SEC,
        )
        if not new_wrapped:
            log.warning(
                "在售一覧点击「%s」后 %.1fs 内未收到新的 MITM 截获 seller_id=%s",
                LISTINGS_LOAD_MORE_TEXT,
                _LISTINGS_AFTER_CLICK_CAPTURE_WAIT_SEC,
                seller_key,
            )
            break

        body = new_wrapped.get("body")
        if not isinstance(body, dict) or body.get("result") != "OK":
            log.warning(
                "在售一覧分页截获异常 seller_id=%s body=%s",
                seller_key,
                body,
            )
            break

        last_ts = int(new_wrapped.get("ts") or last_ts)
        chunk: List[Dict[str, Any]] = body.get("data") or []
        meta = body.get("meta") or meta
        before = len(merged)
        _merge_on_sale_items_by_id(chunk, merged)
        if len(merged) == before and not chunk:
            log.warning(
                "在售一覧分页无新商品 seller_id=%s round=%s",
                seller_key,
                round_idx,
            )
            break

        await _scroll_listings_page_to_bottom(page)

    out_meta = dict(meta)
    total = _meta_total_item_count(out_meta)
    out_meta["has_next"] = (
        False
        if total > 0 and len(merged) >= total
        else bool(out_meta.get("has_next"))
    )
    if total > 0:
        out_meta["total_item_count"] = total
    return list(merged.values()), out_meta


async def capture_on_sale_list_via_mitm_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    seller_key: str,
    *,
    since_ms: int,
    timeout: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    在已建立的 MITM Edge 会话内等待首次 ``items/get_items`` 截获，
    再滚底并展开「もっと見る」分页合并（浏览器须仍为开启状态）。
    """
    await wait_mitm_capture(
        mgr=mgr,
        auto_key=auto_key,
        start_url=LISTINGS_PAGE_URL,
        read_response=lambda: read_on_sale_list_response(seller_key),
        since_ms=since_ms,
        wait_seconds=timeout,
        error_detail=(
            f"在售列表 items/get_items（on_sale,stop），seller_id={seller_key}"
        ),
    )
    page = await mgr.active_tab_page(auto_key)
    return await _expand_on_sale_listings_until_end(page, seller_key)


async def _fetch_on_sale_via_browser_impl(
    account_id: int,
    seller_id: int,
    *,
    timeout: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    seller_key = str(int(seller_id))
    clear_on_sale_list_response_file(seller_key)
    since_ms = int(time.time() * 1000)

    async with mitm_automation_browser(
        account_id,
        start_url=LISTINGS_PAGE_URL,
    ) as (mgr, auto_key):
        return await capture_on_sale_list_via_mitm_session(
            mgr,
            auto_key,
            seller_key,
            since_ms=since_ms,
            timeout=timeout,
        )


async def fetch_on_sale_list_items(
    seller_id: int,
    account_id: Optional[int] = None,
    timeout: int = 90,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    使用对应账号的 Edge 会话（经 MITM）打开出品一覧页，从代理截获的
    ``items/get_items`` 响应中解析 ``data`` 与 ``meta``；按 ``total_item_count`` 滚底并点「もっと見る」加载全部。

    :raises RuntimeError: 未配置 account_id、MITM/浏览器失败或响应 result!=OK
    """
    if account_id is None:
        raise RuntimeError(
            "在售列表改为网页+MITM 截获后，必须提供 account_id（同步入口会传入煤炉账号主键）"
        )
    return await _fetch_on_sale_via_browser_impl(
        int(account_id),
        int(seller_id),
        timeout=int(timeout),
    )


async def sync_on_sale_from_listings_browser_page(
    manager: EdgeWebDriveManager,
    account_key: str,
    seller_id: int,
    page: Any,
    *,
    capture_since_ms: int,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    删除商品后浏览器跳转到出品一覧页时：复用当前有头会话 + MITM，
    截获 items/get_items（on_sale,stop）并执行与「从煤炉同步」相同的本地更新。
    """
    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    seller_key = str(int(seller_id))

    try:
        await page.wait_for_url(
            lambda u: LISTINGS_URL_FRAGMENT in (u or "").lower(),
            timeout=LISTINGS_REDIRECT_TIMEOUT_MS,
        )
    except Exception as exc:
        raise RuntimeError(
            f"删除后未跳转到出品一覧页（{LISTINGS_PAGE_URL}）: {exc}"
        ) from exc

    await wait_mitm_capture(
        mgr=manager,
        auto_key=account_key,
        start_url=LISTINGS_PAGE_URL,
        read_response=lambda: read_on_sale_list_response(seller_key),
        since_ms=capture_since_ms,
        wait_seconds=timeout,
        error_detail=(
            f"在售列表 items/get_items（on_sale,stop），seller_id={seller_key}"
        ),
    )

    from ...on_sale_item_detail_sync import auto_fetch_details_for_inserted_items
    from ...on_sale_items_sync import apply_on_sale_list_sync

    items, meta = await _expand_on_sale_listings_until_end(page, seller_key)
    stats = apply_on_sale_list_sync(seller_key, items, meta)
    stats["auto_detail_fetch"] = await auto_fetch_details_for_inserted_items(
        manager,
        account_key,
        stats.get("inserted_item_ids") or [],
    )
    stats["sync_source"] = "listings_page_after_delete"
    return stats
