# -*- coding: utf-8 -*-
"""
打开 jp.mercari.com/bundle_offer/{bundle_id} 页面，等待 MITM 截获
``/v1/bundlePurchases/{bundle_id}`` 响应。

返回响应体（``body`` 字段，已 ``json.loads``）。
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, Dict, Optional

from ...ssl_mitm_proxy.capture_config import read_bundle_purchase_response
from ...web_drive.core.manager import EdgeWebDriveManager
from ...web_drive.core.mitm_session import wait_mitm_capture

log = logging.getLogger(__name__)

BUNDLE_OFFER_PAGE_URL_TPL = "https://jp.mercari.com/bundle_offer/{bundle_id}"

_PAGE_TIMEOUT_SEC = 45


def build_bundle_offer_url(bundle_id: str) -> str:
    return BUNDLE_OFFER_PAGE_URL_TPL.format(bundle_id=str(bundle_id).strip())


async def capture_bundle_purchase_via_mitm_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    *,
    bundle_id: str,
    since_ms: int,
) -> Optional[Dict[str, Any]]:
    """轮询截获 MITM 写入的 bundle purchase 响应。

    调用方需在打开浏览器**之前**先 ``clear_bundle_purchase_response_file(bundle_id)``
    并取 ``since_ms=int(time.time()*1000)``，否则浏览器首次请求的响应会被本函数误判为旧数据。
    """
    bid = str(bundle_id or "").strip()
    if not bid:
        raise ValueError("bundle_id 不能为空")

    start_url = build_bundle_offer_url(bid)
    data = await wait_mitm_capture(
        mgr=mgr,
        auto_key=auto_key,
        start_url=start_url,
        read_response=partial(read_bundle_purchase_response, bid),
        since_ms=since_ms,
        wait_seconds=_PAGE_TIMEOUT_SEC,
        error_detail=f"v1/bundlePurchases/{bid}",
    )
    body = data.get("body") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        log.warning("[bundle_purchase] 响应体异常 bundle_id=%s", bid)
        return None
    log.info(
        "[bundle_purchase] 抓取完成 bundle_id=%s items=%d",
        bid,
        len(body.get("items") or []),
    )
    return body
