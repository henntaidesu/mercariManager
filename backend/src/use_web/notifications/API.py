# -*- coding: utf-8 -*-
"""お知らせ通知 API 路由（对应前端 /notifications 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/notifications
- 完整 URL 示例:
    GET   /mercariV2/src/use_web/notifications
    POST  /mercariV2/src/use_web/notifications/sync
    GET   /mercariV2/src/use_web/notifications/kinds
    POST  /mercariV2/src/use_web/notifications/mark-read
    POST  /mercariV2/src/use_web/notifications/mark-all-read

合并购买请求（BundleRequestCreated）相关：
    POST  /mercariV2/src/use_web/notifications/bundle-purchase/sync
    GET   /mercariV2/src/use_web/notifications/bundle-purchase/{bundle_id}
    POST  /mercariV2/src/use_web/notifications/bundle-purchase/{bundle_id}/decide
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ...use_mercari.get_notifications.bundle_purchase_decide import (
    decide_bundle_purchase,
)
from .units.bundle_purchase_models import (
    BundlePurchaseDecideRequest,
    BundlePurchaseSyncRequest,
)
from .units.bundle_purchase_query import get_bundle_purchase
from .units.bundle_purchase_sync import sync_bundle_purchase
from .units.notifications_models import MarkReadRequest, SyncNotificationsRequest
from .units.notifications_query import (
    list_kinds,
    list_notifications,
    mark_all_read,
    mark_read,
)
from .units.notifications_sync import sync_notifications

router = APIRouter()


def _list_notifications_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    return list_notifications(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        only_unread=only_unread,
        page=page,
        page_size=page_size,
    )


def _list_kinds_endpoint() -> Dict[str, Any]:
    return {"kinds": list_kinds()}


def _mark_read_endpoint(req: MarkReadRequest) -> Dict[str, Any]:
    return mark_read(req.ids, is_read=req.is_read)


def _mark_all_read_endpoint(account_id: Optional[int] = None) -> Dict[str, Any]:
    return mark_all_read(account_id=account_id)


async def _sync_endpoint(req: SyncNotificationsRequest) -> Dict[str, Any]:
    return await sync_notifications(req)


# ─────────── 合并购买请求 ───────────


async def _bundle_purchase_sync_endpoint(req: BundlePurchaseSyncRequest) -> Dict[str, Any]:
    return await sync_bundle_purchase(req)


def _bundle_purchase_detail_endpoint(
    bundle_id: str, account_id: Optional[int] = None
) -> Dict[str, Any]:
    row = get_bundle_purchase(bundle_id, account_id=account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到合并购买请求，请先「同步」一次")
    return row


async def _bundle_purchase_decide_endpoint(
    bundle_id: str, req: BundlePurchaseDecideRequest
) -> Dict[str, Any]:
    """承诺 / 拒绝合并购买请求。不走队列：直接复用主 profile 浏览器、点击后关闭。"""
    act = (req.action or "").strip().lower()
    if act not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 accept / reject")
    if act == "accept":
        missing = [
            name
            for name, val in (
                ("shipping_payer", req.shipping_payer),
                ("shipping_method", req.shipping_method),
                ("shipping_from", req.shipping_from),
                ("shipping_days", req.shipping_days),
            )
            if not (val or "").strip()
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"承诺前必须填写以下字段: {', '.join(missing)}",
            )
    try:
        return await decide_bundle_purchase(
            bundle_id=bundle_id,
            account_id=req.account_id,
            action=act,
            shipping_payer=req.shipping_payer,
            shipping_method=req.shipping_method,
            shipping_from=req.shipping_from,
            shipping_days=req.shipping_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


router.add_api_route("", _list_notifications_endpoint, methods=["GET"])
router.add_api_route("/kinds", _list_kinds_endpoint, methods=["GET"])
router.add_api_route("/sync", _sync_endpoint, methods=["POST"])
router.add_api_route("/mark-read", _mark_read_endpoint, methods=["POST"])
router.add_api_route("/mark-all-read", _mark_all_read_endpoint, methods=["POST"])

router.add_api_route(
    "/bundle-purchase/sync", _bundle_purchase_sync_endpoint, methods=["POST"]
)
router.add_api_route(
    "/bundle-purchase/{bundle_id}", _bundle_purchase_detail_endpoint, methods=["GET"]
)
router.add_api_route(
    "/bundle-purchase/{bundle_id}/decide",
    _bundle_purchase_decide_endpoint,
    methods=["POST"],
)
