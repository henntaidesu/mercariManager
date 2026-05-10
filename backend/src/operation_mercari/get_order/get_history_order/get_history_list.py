# -*- coding: utf-8 -*-
"""
获取 Mercari 已售完（sold_out）历史订单列表并同步到本地订单管理表。

列表数据：使用账号 WebDriver 打开 ``https://jp.mercari.com/mypage/listings/completed``（MITM），
截获 ``GET https://api.mercari.jp/items/get_items``（status=sold_out）响应，不再直连 API。

数据映射与 get_order_list 相同，复用其 _item_to_order_data / _upsert_order。
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from ....ssl_mitm_proxy.capture_config import (
    clear_sold_out_list_response_file,
    read_sold_out_list_response,
)
from ....ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy
from ....web_drive import get_web_drive_manager
from ..get_in_progress_order.get_order_info import apply_item_info_to_order
from ..get_in_progress_order.get_order_list import _item_to_order_data, _upsert_order

_API_URL = "https://api.mercari.jp/items/get_items"
_API_PARAMS = (
    "order_by=desc"
    "&sort_type=updated"
    "&status=sold_out"
    "&with_auction=true"
    "&with_enhanced_hints=false"
    "&with_impression_boost=false"
)

COMPLETED_PAGE_URL = "https://jp.mercari.com/mypage/listings/completed"


def _mitm_browser_headless() -> bool:
    v = (
        os.environ.get("WEB_DRIVE_MERCARI_HEADLESS")
        or os.environ.get("WEB_DRIVE_ON_SALE_SYNC_HEADLESS")
        or "1"
    ).strip().lower()
    return v in ("1", "true", "yes", "on")


async def _wait_sold_out_mitm_response(
    *,
    seller_key: str,
    since_ms: int,
    wait_seconds: int,
) -> Dict[str, Any]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        data = read_sold_out_list_response(seller_key)
        if data and int(data.get("ts") or 0) >= since_ms:
            return data
        await asyncio.sleep(0.35)
    raise RuntimeError(
        f"{wait_seconds}s 内未截获已售完列表 items/get_items（sold_out）（请确认 MITM 已启动、"
        f"账号已登录且 seller_id={seller_key}）"
    )


async def _fetch_sold_out_list_via_browser_impl(
    account_id: int,
    seller_id: int,
    *,
    timeout: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    seller_key = str(int(seller_id))
    clear_sold_out_list_response_file(seller_key)
    since_ms = int(time.time() * 1000)

    mgr = get_web_drive_manager()
    key = f"meilu_{account_id}"
    proxy = default_mitm_proxy_url()
    headless = _mitm_browser_headless()

    try:
        await mgr.close_session(key)
        await mgr.open_session(
            key,
            headless=headless,
            start_url=COMPLETED_PAGE_URL,
            proxy_server=proxy,
        )
        await _wait_sold_out_mitm_response(
            seller_key=seller_key,
            since_ms=since_ms,
            wait_seconds=timeout,
        )
    finally:
        try:
            await mgr.close_session(key)
        except Exception:
            pass

    wrapped = read_sold_out_list_response(seller_key) or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"截获的已售完列表格式异常: {wrapped!r}")
    if body.get("result") != "OK":
        raise RuntimeError(f"历史订单 API 返回异常: {body}")

    items: List[Dict[str, Any]] = body.get("data") or []
    meta: Dict[str, Any] = body.get("meta") or {}
    return items, meta


def fetch_history_order_items(
    seller_id: int,
    account_id: Optional[int] = None,
    timeout: int = 90,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    使用 ``meilu_{account_id}`` 打开「取引完了」一覧页，从 MITM 截获的 items/get_items（sold_out）解析列表。
    """
    if account_id is None:
        raise RuntimeError(
            "历史列表改为网页+MITM 截获后，必须提供 account_id（同步入口会传入煤炉账号主键）"
        )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            _fetch_sold_out_list_via_browser_impl(
                int(account_id),
                int(seller_id),
                timeout=int(timeout),
            )
        )
    raise RuntimeError(
        "fetch_history_order_items 须在无运行中 event loop 的线程内调用（例如 FastAPI 同步路由）"
    )


def fetch_and_sync_history_orders(
    seller_id: int,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    从 Mercari 取引完了一覧（网页 + MITM）获取已售完订单列表，并同步到本地订单管理表（与交易中订单同表）。

    :param seller_id:  Mercari 卖家 ID（从账号配置读取后传入）。
    :param account_id: 指定煤炉账号 ID（WebDriver profile ``meilu_{id}``）。
    :return: 同步结果统计字典。
    """
    items, meta = fetch_history_order_items(seller_id=seller_id, account_id=account_id)

    stats = {
        "total": len(items),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "info_enriched": 0,
        "info_errors": [],
    }

    for item in items:
        try:
            order_data = _item_to_order_data(item, seller_id=seller_id)
            result = _upsert_order(order_data)
            stats[result] += 1
            iid = item.get("id")
            if iid and result in ("inserted", "updated"):
                err = apply_item_info_to_order(str(iid), account_id=account_id)
                if err is None:
                    stats["info_enriched"] += 1
                else:
                    stats["info_errors"].append({"item_id": iid, "error": err})
        except Exception as exc:
            stats["errors"].append({"item_id": item.get("id"), "error": str(exc)})

    stats["has_next"] = meta.get("has_next", False)
    stats["total_item_count"] = meta.get("total_item_count", len(items))

    print(
        f"[history_orders] 同步完成: "
        f"共 {stats['total']} 条, "
        f"新增 {stats['inserted']}, "
        f"更新 {stats['updated']}, "
        f"跳过 {stats['skipped']}, "
        f"错误 {len(stats['errors'])}, "
        f"info 回填 {stats['info_enriched']}, "
        f"info 失败 {len(stats['info_errors'])}"
    )
    if stats["info_errors"]:
        fe = stats["info_errors"][0]
        print(f"  [history_orders] info 失败示例: item_id={fe.get('item_id')!r} -> {fe.get('error')!r}")
    return stats
