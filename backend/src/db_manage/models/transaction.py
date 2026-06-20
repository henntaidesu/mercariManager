# -*- coding: utf-8 -*-
"""
出入库记录表模型。

created_at：INTEGER，Unix 秒；存量库由 scripts/migrate_transactions_created_at.py 自 DATETIME 转换。
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from ..base_model import BaseModel
from .warehouse import WarehouseModel


def _local_today_unix_bounds() -> Tuple[int, int]:
    """本地日历日 [0:00, 次日 0:00) 的 Unix 秒，与 INTEGER created_at 比较。"""
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


class TransactionModel(BaseModel):
    """出入库记录表（type: in=入库 / out=出库 / transfer=调拨）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "transactions"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'type': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'inventory_id': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
            'warehouse_id': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
            'target_warehouse_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
            'remark': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'operator': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'管理员'",
            },
            # Unix 秒；插入时若未赋值由 save() 填当前秒（避免在模型 default 里写 SQL 污染 Python 字段）
            'created_at': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
        }

    def save(self) -> bool:
        if self._is_new_record():
            ca = self._data.get("created_at")
            if ca is None:
                self._data["created_at"] = int(time.time())
        return super().save()

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_transactions_inventory', 'columns': ['inventory_id']},
            {'name': 'idx_transactions_warehouse', 'columns': ['warehouse_id']},
            {'name': 'idx_transactions_target_warehouse', 'columns': ['target_warehouse_id']},
            {'name': 'idx_transactions_created', 'columns': ['created_at']},
        ]

    @classmethod
    def find_detail_list(
        cls,
        tx_type: Optional[str] = None,
        inventory_id: Optional[int] = None,
        warehouse_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询出入库记录列表（含分页），附带商品和仓库名称"""
        db = cls().db
        base_sql = """
            FROM [transactions] t
            LEFT JOIN [inventory] p ON p.id = t.inventory_id
            LEFT JOIN [warehouses] w ON w.id = t.warehouse_id
            LEFT JOIN [warehouses] tw ON tw.id = t.target_warehouse_id
            WHERE 1=1
        """
        params = []
        if tx_type:
            base_sql += " AND t.type = ?"
            params.append(tx_type)
        if inventory_id:
            base_sql += " AND t.inventory_id = ?"
            params.append(inventory_id)
        if warehouse_id:
            base_sql += " AND (t.warehouse_id = ? OR t.target_warehouse_id = ?)"
            params += [warehouse_id, warehouse_id]

        filter_params = list(params)

        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(filter_params))[0][0]

        t_start, t_end = _local_today_unix_bounds()
        time_clause = " AND t.created_at >= ? AND t.created_at < ?"
        today_params = tuple(filter_params + [t_start, t_end])

        today_in = int(
            db.execute_query(
                f"SELECT COALESCE(SUM(t.quantity), 0) {base_sql}{time_clause} AND t.type = 'in'",
                today_params,
            )[0][0]
        )
        today_out = int(
            db.execute_query(
                f"SELECT COALESCE(SUM(t.quantity), 0) {base_sql}{time_clause} AND t.type = 'out'",
                today_params,
            )[0][0]
        )

        wh_l = WarehouseModel.sql_display_label("w")
        tw_l = WarehouseModel.sql_display_label("tw")
        select_sql = f"""
            SELECT t.id, t.type, t.inventory_id,
                   COALESCE(NULLIF(p.name, ''), '[ID:' || t.inventory_id || '] 库存已删除') as inventory_name,
                   t.warehouse_id, {wh_l} as warehouse_name,
                   t.target_warehouse_id, {tw_l} as target_warehouse_name,
                   t.quantity, t.remark, t.operator, t.created_at
            {base_sql}
            ORDER BY t.created_at DESC
            LIMIT ? OFFSET ?
        """
        list_params = tuple(filter_params + [page_size, (page - 1) * page_size])
        rows = db.execute_query(select_sql, list_params)

        keys = ['id', 'type', 'inventory_id', 'inventory_name',
                'warehouse_id', 'warehouse_name',
                'target_warehouse_id', 'target_warehouse_name',
                'quantity', 'remark', 'operator', 'created_at']
        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'today_in': today_in,
            'today_out': today_out,
            'items': [dict(zip(keys, row)) for row in rows],
        }
