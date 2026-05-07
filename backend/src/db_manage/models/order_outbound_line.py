# -*- coding: utf-8 -*-
"""
订单待出库明细：从商品说明解析「管理ID:」「バーコード:」等后写入，用于订单二级列表与库存「待出库数量」汇总。
"""

from typing import Any, Dict, List, Optional, Tuple

from ..base_model import BaseModel


# 以下状态的订单不再占用待出库数量（与业务终态一致）
TERMINAL_ORDER_STATUSES: Tuple[str, ...] = (
    "done",
    "sold_out",
    "cancelled",
    "cancel_request",
)


class OrderOutboundLineModel(BaseModel):
    """order_outbound_lines：一行对应说明里解析出的一个管理 ID 或一条条码（映射 inventory）。"""

    @classmethod
    def get_table_name(cls) -> str:
        return "order_outbound_lines"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "order_no": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "inventory_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "management_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            # mgmt_id：管理番号（inventory.id）；barcode：说明中的条码串（匹配 inventory.barcode）
            "line_kind": {
                "type": "TEXT",
                "not_null": True,
                "default": "'mgmt_id'",
            },
            "quantity": {
                "type": "INTEGER",
                "not_null": True,
                "default": 1,
            },
            "sort_index": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "is_stocked_out": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "stocked_out_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {"name": "idx_obl_order_no", "columns": ["order_no"], "unique": False},
            {"name": "idx_obl_inventory_id", "columns": ["inventory_id"], "unique": False},
        ]

    @classmethod
    def list_enriched_for_order(cls, order_no: str) -> List[Dict[str, Any]]:
        """返回某订单解析出的出库行，左联库存与仓库名称（不按订单状态过滤，便于查看历史单）。"""
        ono = (order_no or "").strip()
        if not ono:
            return []
        db = cls().db
        sql = f"""
            SELECT
                l.id,
                l.order_no,
                l.inventory_id,
                l.management_id,
                l.line_kind,
                l.quantity,
                l.sort_index,
                COALESCE(l.is_stocked_out, 0) AS is_stocked_out,
                l.stocked_out_at,
                p.name AS product_name,
                p.barcode AS product_barcode,
                p.sku AS product_sku,
                p.quantity AS stock_quantity,
                COALESCE(u.display_name, u.username) AS product_owner_name,
                COALESCE(NULLIF(TRIM(w.[warehouse]), ''), '默认仓库') AS warehouse_name,
                NULLIF(TRIM(w.[shelf_name]), '') AS shelf_name,
                NULLIF(TRIM(w.[name]), '') AS shelf_code
            FROM [{cls.get_table_name()}] l
            LEFT JOIN [inventory] p ON p.id = l.inventory_id
            LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
            LEFT JOIN [users] u ON u.id = p.owner_user_id
            WHERE l.order_no = ?
            ORDER BY l.sort_index ASC, l.id ASC
        """
        rows = db.execute_query(sql, (ono,))
        keys = [
            "id",
            "order_no",
            "inventory_id",
            "management_id",
            "line_kind",
            "quantity",
            "sort_index",
            "is_stocked_out",
            "stocked_out_at",
            "product_name",
            "product_barcode",
            "product_sku",
            "stock_quantity",
            "product_owner_name",
            "warehouse_name",
            "shelf_name",
            "shelf_code",
        ]
        return [dict(zip(keys, r)) for r in rows]
