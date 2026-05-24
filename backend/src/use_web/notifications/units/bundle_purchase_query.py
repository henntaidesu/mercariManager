# -*- coding: utf-8 -*-
"""
合并购买请求查询（DB 层）。
"""

import json
from typing import Any, Dict, Optional

from ....db_manage.database import DatabaseManager

_DETAIL_COLS = (
    "id",
    "account_id",
    "bundle_id",
    "notification_id",
    "seller_id",
    "buyer_id",
    "buyer_username",
    "suggested_price",
    "original_price",
    "state",
    "items_json",
    "raw_json",
    "bundle_created",
    "bundle_expire",
    "form_shipping_payer",
    "form_shipping_method",
    "form_shipping_from",
    "form_shipping_days",
    "form_updated_at",
    "synced_at",
)


def _safe_json_loads(s: Any) -> Any:
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_dict(row: tuple) -> Dict[str, Any]:
    d = dict(zip(_DETAIL_COLS, row))
    d["items"] = _safe_json_loads(d.get("items_json")) or []
    d["raw"] = _safe_json_loads(d.get("raw_json"))
    return d


def get_bundle_purchase(
    bundle_id: str, account_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """按 bundle_id 取出合并购买请求详情；account_id 可选用于多账号隔离。"""
    bid = str(bundle_id or "").strip()
    if not bid:
        return None
    db = DatabaseManager()
    sel_cols = ", ".join(f"[{c}]" for c in _DETAIL_COLS)
    if account_id is not None:
        rows = db.execute_query(
            f"SELECT {sel_cols} FROM [bundle_purchase_requests] "
            "WHERE [bundle_id] = ? AND [account_id] = ? LIMIT 1",
            (bid, int(account_id)),
        )
    else:
        rows = db.execute_query(
            f"SELECT {sel_cols} FROM [bundle_purchase_requests] "
            "WHERE [bundle_id] = ? ORDER BY [id] DESC LIMIT 1",
            (bid,),
        )
    if not rows:
        return None
    return _row_to_dict(rows[0])


