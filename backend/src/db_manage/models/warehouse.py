# -*- coding: utf-8 -*-
"""
仓库表模型
"""

from typing import Dict, Any, List
from ..base_model import BaseModel


class WarehouseModel(BaseModel):
    """仓库表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "warehouses"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 货架名称（展示用）；业务主键为 id；同一仓库下货架号可重复
            'shelf_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 节点类型：warehouse=空白仓库占位 / shelf=货架(货架名称) / shelf_no=货架号(叶子，承载库存)
            'node_type': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'warehouse': {
                'type': 'TEXT',
                'not_null': False,
                'default': '默认仓库',
            },
            'location': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'idx_warehouses_warehouse_name',
                'columns': ['warehouse', 'name'],
                'unique': False,
            },
        ]

    @classmethod
    def normalize_warehouse_key(cls, warehouse: Any) -> str:
        if warehouse is None:
            return '默认仓库'
        t = str(warehouse).strip()
        return t if t else '默认仓库'

    @classmethod
    def find_by_name(cls, name: str):
        """根据货架名称查找（仍可能有同名跨仓库，谨慎使用）"""
        result = cls.find_all("name = ?", (name,), limit=1)
        return result[0] if result else None

    @classmethod
    def get_stats(cls, warehouse_id: int) -> Dict[str, int]:
        """获取仓库统计（基于 transactions 计算净库存）"""
        db = cls().db
        total_qty = db.execute_query(
            """
            SELECT COALESCE(SUM(
                CASE
                    WHEN type = 'in' AND warehouse_id = ? THEN quantity
                    WHEN type = 'out' AND warehouse_id = ? THEN -quantity
                    WHEN type = 'transfer' AND warehouse_id = ? THEN -quantity
                    WHEN type = 'transfer' AND target_warehouse_id = ? THEN quantity
                    ELSE 0
                END
            ), 0)
            FROM [transactions]
            """,
            (warehouse_id, warehouse_id, warehouse_id, warehouse_id)
        )
        product_types = db.execute_query(
            """
            SELECT COUNT(*) FROM (
                SELECT inventory_id,
                       SUM(
                           CASE
                               WHEN type = 'in' AND warehouse_id = ? THEN quantity
                               WHEN type = 'out' AND warehouse_id = ? THEN -quantity
                               WHEN type = 'transfer' AND warehouse_id = ? THEN -quantity
                               WHEN type = 'transfer' AND target_warehouse_id = ? THEN quantity
                               ELSE 0
                           END
                       ) AS net_qty
                FROM [transactions]
                GROUP BY inventory_id
                HAVING net_qty > 0
            ) t
            """,
            (warehouse_id, warehouse_id, warehouse_id, warehouse_id)
        )
        return {
            'total_quantity': total_qty[0][0] if total_qty else 0,
            'product_types': product_types[0][0] if product_types else 0,
        }

    @classmethod
    def get_stats_all(cls) -> Dict[int, Dict[str, int]]:
        """一次性返回 {warehouse_id: {total_quantity, product_types}}，口径与 get_stats 完全一致，
        但用一条按 (仓库, 商品) 聚合的查询替代「逐仓库 2 次全表扫描」的 N+1。

        每笔 transactions 对仓位的净增减：in/out/transfer 计入 warehouse_id（in 加、out/transfer 减），
        transfer 另把数量计入 target_warehouse_id。total_quantity = 该仓位所有净增减之和；
        product_types = 该仓位下「按商品聚合后净库存 > 0」的商品种类数。
        """
        db = cls().db
        rows = db.execute_query(
            """
            SELECT wh, SUM(net) AS total_quantity,
                   SUM(CASE WHEN net > 0 THEN 1 ELSE 0 END) AS product_types
            FROM (
                SELECT wh, inventory_id, SUM(delta) AS net
                FROM (
                    SELECT warehouse_id AS wh, inventory_id,
                           CASE type
                               WHEN 'in' THEN quantity
                               WHEN 'out' THEN -quantity
                               WHEN 'transfer' THEN -quantity
                               ELSE 0
                           END AS delta
                    FROM [transactions]
                    WHERE warehouse_id IS NOT NULL
                    UNION ALL
                    SELECT target_warehouse_id AS wh, inventory_id, quantity AS delta
                    FROM [transactions]
                    WHERE type = 'transfer' AND target_warehouse_id IS NOT NULL
                )
                GROUP BY wh, inventory_id
            )
            GROUP BY wh
            """
        )
        out: Dict[int, Dict[str, int]] = {}
        for r in rows or []:
            if r is None or r[0] is None:
                continue
            out[int(r[0])] = {
                'total_quantity': int(r[1] or 0),
                'product_types': int(r[2] or 0),
            }
        return out

    @classmethod
    def sql_display_label(cls, alias: str = "w") -> str:
        """JOIN warehouses AS {alias} 时，列表展示的仓位文案：有货架名称则「名称（货架号）」否则货架号"""
        a = alias.strip() or "w"
        return (
            f"(CASE WHEN NULLIF(TRIM({a}.shelf_name), '') IS NOT NULL "
            f"THEN TRIM({a}.shelf_name) || '（' || COALESCE({a}.name, '') || '）' "
            f"ELSE COALESCE({a}.name, '-') END)"
        )
