# -*- coding: utf-8 -*-
"""
打开 jp.mercari.com/item/{item_id} 页面，等待 MITM 截获
``api.mercari.jp/items/get?id={item_id}`` 响应。

返回响应体（``body`` 字段，已 ``json.loads``）。
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, Dict, List, Optional

from ...ssl_mitm_proxy.capture_config import read_item_get_response
from ...web_drive.core.manager import EdgeWebDriveManager
from ...web_drive.core.mitm_session import wait_mitm_capture

log = logging.getLogger(__name__)

ITEM_PAGE_URL_TPL = "https://jp.mercari.com/item/{item_id}"

_PAGE_TIMEOUT_SEC = 45


def build_item_page_url(item_id: str) -> str:
    return ITEM_PAGE_URL_TPL.format(item_id=str(item_id).strip())


def normalize_comment(raw: Any) -> Optional[Dict[str, Any]]:
    """items/get 响应中单条 comment → 前端使用的扁平结构。"""
    if not isinstance(raw, dict):
        return None
    user = raw.get("user") if isinstance(raw.get("user"), dict) else {}
    return {
        "id": raw.get("id"),
        "user_id": user.get("id"),
        "user_name": user.get("name"),
        "user_photo": user.get("photo_thumbnail_url") or user.get("photo_url"),
        "message": raw.get("message"),
        # mercari 用秒级 unix ts;前端按毫秒处理统一,这里转成 ms
        "created_ms": int(raw.get("created") or 0) * 1000 if raw.get("created") else None,
    }


def build_item_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    """从 items/get 的 data 子对象中提取前端需要的最小字段。"""
    seller = data.get("seller") if isinstance(data.get("seller"), dict) else {}
    thumbnails = data.get("thumbnails") if isinstance(data.get("thumbnails"), list) else []
    photos = data.get("photos") if isinstance(data.get("photos"), list) else []
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "price": data.get("price"),
        "status": data.get("status"),
        "thumbnail": (thumbnails[0] if thumbnails else (photos[0] if photos else None)),
        "num_comments": data.get("num_comments"),
        "seller_id": seller.get("id"),
        "seller_name": seller.get("name"),
        "seller_photo": seller.get("photo_thumbnail_url") or seller.get("photo_url"),
    }


def extract_item_with_comments(data: Dict[str, Any]) -> Dict[str, Any]:
    """items/get 的 data 子对象 → {item, comments}。"""
    raw_comments = data.get("comments") or []
    comments: List[Dict[str, Any]] = []
    for c in raw_comments:
        norm = normalize_comment(c)
        if norm is not None:
            comments.append(norm)
    return {"item": build_item_summary(data), "comments": comments}


async def capture_item_get_via_mitm_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    *,
    item_id: str,
    since_ms: int,
) -> Optional[Dict[str, Any]]:
    """轮询截获 MITM 写入的 items/get 响应。

    调用方需在打开浏览器**之前**先 ``clear_item_get_response_file(item_id)``
    并取 ``since_ms=int(time.time()*1000)``。
    """
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")

    start_url = build_item_page_url(iid)
    data = await wait_mitm_capture(
        mgr=mgr,
        auto_key=auto_key,
        start_url=start_url,
        read_response=partial(read_item_get_response, iid),
        since_ms=since_ms,
        wait_seconds=_PAGE_TIMEOUT_SEC,
        error_detail=f"items/get?id={iid}",
    )
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        log.warning("[item_comment] items/get 响应体异常 item_id=%s", iid)
        return None
    # data.data 是真正的商品对象
    inner = body.get("data") if isinstance(body, dict) else None
    if not isinstance(inner, dict):
        log.warning("[item_comment] items/get body.data 异常 item_id=%s", iid)
        return None
    log.info(
        "[item_comment] 抓取完成 item_id=%s name=%r comments=%d",
        iid,
        inner.get("name"),
        len(inner.get("comments") or []),
    )
    return inner
