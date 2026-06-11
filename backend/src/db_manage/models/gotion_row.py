# -*- coding: utf-8 -*-
"""Gotion 表格管理 - 行数据模型（JSON 存储灵活字段）"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from ..base_model import BaseModel


class GotionRowModel(BaseModel):
    """gotion 自定义表的行数据"""

    @classmethod
    def get_table_name(cls) -> str:
        return 'gotion_rows'

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id':         {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            'table_id':   {'type': 'INTEGER', 'not_null': True},
            'data':       {'type': 'TEXT',    'not_null': False, 'default': None},  # JSON
            'sort_order': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'created_at': {'type': 'TEXT',    'not_null': False, 'default': None},
            'updated_at': {'type': 'TEXT',    'not_null': False, 'default': None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_gotion_rows_table', 'columns': ['table_id']},
            {'name': 'idx_gotion_rows_sort',  'columns': ['table_id', 'sort_order']},
        ]

    def save(self) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        if not self._data.get('created_at'):
            self._data['created_at'] = now
        self._data['updated_at'] = now
        # 序列化 data dict -> JSON string
        if isinstance(self._data.get('data'), dict):
            self._data['data'] = json.dumps(self._data['data'], ensure_ascii=False)
        return super().save()

    def get_data_dict(self) -> Dict[str, Any]:
        """将 JSON data 字段解析为 dict"""
        raw = self._data.get('data')
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d['data'] = self.get_data_dict()
        return d

    @classmethod
    def find_by_table(cls, table_id: int) -> List['GotionRowModel']:
        return cls.find_all(
            where='[table_id] = ?',
            params=(table_id,),
            order_by='[sort_order] ASC, [id] ASC'
        )

    @classmethod
    def get_next_sort_order(cls, table_id: int) -> int:
        db = cls().db
        result = db.execute_query(
            f"SELECT MAX(sort_order) FROM [{cls.get_table_name()}] WHERE table_id = ?",
            (table_id,)
        )
        max_order = result[0][0] if result and result[0][0] is not None else -1
        return max_order + 1

    @classmethod
    def find_by_table_filtered(cls, table_id: int, filter_col: str, filter_val: str) -> List['GotionRowModel']:
        """通过 JSON data 内的字段值过滤行（支持数组值与标量值）"""
        rows = cls.find_by_table(table_id)
        result = []
        for row in rows:
            data = row.get_data_dict()
            cell_val = data.get(filter_col)
            if cell_val is None:
                continue
            if isinstance(cell_val, list):
                if str(filter_val) in [str(v) for v in cell_val]:
                    result.append(row)
            else:
                if str(cell_val) == str(filter_val):
                    result.append(row)
        return result
