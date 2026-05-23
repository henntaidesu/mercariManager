# -*- coding: utf-8 -*-
"""
Mercari 单件商品详情：经 WebDriver 打开 ``https://jp.mercari.com/item/m…``（MITM），
截获 ``GET https://api.mercari.jp/items/get?id=…`` 的 JSON 响应，不再直连 API。

历史 ``build_mercari_item_get_url`` 的查询串仍可用于对照抓包；DPoP 头不再参与请求。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional
from urllib.parse import quote

from ...ssl_mitm_proxy.capture_config import (
    canonical_mercari_item_id,
    clear_item_get_response_file,
    read_item_get_response,
)
from ...web_drive.core.manager import EdgeWebDriveManager
from ...web_drive.core.mitm_session import mitm_automation_browser

_ITEM_GET_BASE = "https://api.mercari.jp/items/get"
# 与 App / 测试样例一致的查询参数（顺序固定便于抓包对照）
_ITEM_GET_SUFFIX = (
    "include_auction=true"
    "&include_campaign_achievement_status=false"
    "&include_donation=true"
    "&include_impboost=true"
    "&include_item_attributes=true"
    "&include_item_attributes_sections=true"
    "&include_non_ui_item_attributes=true"
    "&include_offer_coupon_display=true"
    "&include_offer_like_coupon_display=false"
    "&include_product_page_component=true"
)


def build_mercari_item_get_url(item_id: str) -> str:
    raw = str(item_id or "").strip()
    if not raw:
        raise ValueError("item_id 不能为空")
    qid = quote(raw, safe="")
    return f"{_ITEM_GET_BASE}?id={qid}&{_ITEM_GET_SUFFIX}"


def mercari_item_page_url(item_id: str) -> str:
    """商品前台页，例如 ``https://jp.mercari.com/item/m74794255985``。"""
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        raise ValueError("item_id 不能为空")
    return f"https://jp.mercari.com/item/{cid}"


async def _wait_item_get_mitm_response(
    *,
    item_id: str,
    since_ms: int,
    wait_seconds: int,
) -> Dict[str, Any]:
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        raise RuntimeError("item_id 不能为空")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        data = read_item_get_response(cid)
        if data and int(data.get("ts") or 0) >= since_ms:
            return data
        await asyncio.sleep(0.35)
    raise RuntimeError(
        f"{wait_seconds}s 内未截获商品详情 items/get（请确认 MITM 已启动、"
        f"账号已登录，商品 id={cid}）"
    )


async def fetch_mercari_item_get_in_browser_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    item_id: str,
    *,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    在已打开的 MITM Edge 会话（与在售列表同步同款 ``meilu_{id}__auto``）内导航到商品页，
    截获 ``items/get`` JSON（含 result / data），供 ``detail_sync_inventory_from_item_get_response`` 使用。
    """
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        raise RuntimeError("item_id 不能为空")
    clear_item_get_response_file(cid)
    since_ms = int(time.time() * 1000)
    page_url = mercari_item_page_url(cid)
    await mgr.reload_active_tab(auto_key, page_url)
    await _wait_item_get_mitm_response(
        item_id=cid,
        since_ms=since_ms,
        wait_seconds=int(timeout),
    )
    wrapped = read_item_get_response(cid) or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"截获的商品详情格式异常: {wrapped!r}")
    return body


async def _fetch_mercari_item_get_via_browser_impl(
    item_id: str,
    account_id: int,
    *,
    timeout: int,
) -> Dict[str, Any]:
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        raise RuntimeError("item_id 不能为空")

    clear_item_get_response_file(cid)
    since_ms = int(time.time() * 1000)
    page_url = mercari_item_page_url(cid)

    async with mitm_automation_browser(
        account_id,
        start_url=page_url,
    ) as (mgr, auto_key):
        await fetch_mercari_item_get_in_browser_session(
            mgr,
            auto_key,
            cid,
            timeout=int(timeout),
        )

    wrapped = read_item_get_response(cid) or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"截获的商品详情格式异常: {wrapped!r}")

    return body


async def fetch_mercari_item_get(
    item_id: str,
    account_id: Optional[int] = None,
    *,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    使用账号 Edge（``meilu_{account_id}``）打开商品页，返回 MITM 截获的
    ``items/get`` 完整 JSON（含 result / data）。

    :raises RuntimeError: 未提供 account_id、MITM/浏览器失败或截获体无效
    """
    if account_id is None:
        raise RuntimeError(
            "商品详情改为网页+MITM 截获后，必须提供 account_id（获取详情接口会解析煤炉账号主键）"
        )
    return await _fetch_mercari_item_get_via_browser_impl(
        str(item_id).strip(),
        int(account_id),
        timeout=int(timeout),
    )
