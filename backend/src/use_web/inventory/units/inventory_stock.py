# -*- coding: utf-8 -*-
"""库存入库/出库端点（连续扫码场景）。"""
import time
from fastapi import HTTPException

from ....db_manage.database import DatabaseManager

from .inventory_helpers import _inventory_exists
from .inventory_combined import _parse_combined_items, _adjust_combined_source_stock
from .inventory_models import StockInRequest

db = DatabaseManager()


def stock_in_inventory(pid: int, data: StockInRequest):
    """连续扫码入库：库存 +N；若提供 warehouse_id 则同时写入事务记录"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="入库数量必须大于0")
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT is_combined, combined_items FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
            meta = cur.fetchone()
            if not meta:
                raise HTTPException(status_code=404, detail="商品不存在")
            if int(meta[0] or 0):
                _adjust_combined_source_stock(cur, _parse_combined_items(meta[1]), int(data.quantity))
            cur.execute(
                "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) + ? WHERE id = ?",
                (data.quantity, pid),
            )
            if cur.rowcount <= 0:
                raise HTTPException(status_code=500, detail="库存更新失败")
            cur.execute(
                "UPDATE [inventory] SET [listable_quantity] = "
                "MAX(0, COALESCE([quantity],0) - COALESCE([on_sale_quantity],0) - COALESCE([pending_outbound_qty],0)) "
                "WHERE id = ?",
                (pid,),
            )
            if data.warehouse_id:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "in",
                        pid,
                        data.warehouse_id,
                        data.quantity,
                        data.remark or "扫码快速入库",
                        int(time.time()),
                    ),
                )
            conn.commit()
    except HTTPException:
        raise
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}


def stock_out_inventory(pid: int, data: StockInRequest):
    """连续扫码出库：库存 -N；若提供 warehouse_id 则同时写入事务记录"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="出库数量必须大于0")
    current_qty_row = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
    current_qty = (current_qty_row[0][0] if current_qty_row else 0) or 0
    if current_qty < data.quantity:
        raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT is_combined, combined_items, quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
            meta = cur.fetchone()
            if not meta:
                raise HTTPException(status_code=404, detail="商品不存在")
            if int(meta[2] or 0) < data.quantity:
                raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{int(meta[2] or 0)}")
            if int(meta[0] or 0):
                _adjust_combined_source_stock(cur, _parse_combined_items(meta[1]), -int(data.quantity))
            cur.execute(
                "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) - ? WHERE id = ?",
                (data.quantity, pid),
            )
            if cur.rowcount <= 0:
                raise HTTPException(status_code=500, detail="库存更新失败")
            cur.execute(
                "UPDATE [inventory] SET [listable_quantity] = "
                "MAX(0, COALESCE([quantity],0) - COALESCE([on_sale_quantity],0) - COALESCE([pending_outbound_qty],0)) "
                "WHERE id = ?",
                (pid,),
            )
            if data.warehouse_id:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        pid,
                        data.warehouse_id,
                        data.quantity,
                        data.remark or "扫码快速出库",
                        int(time.time()),
                    ),
                )
            conn.commit()
    except HTTPException:
        raise
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}
