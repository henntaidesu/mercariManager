# -*- coding: utf-8 -*-
"""Gotion 表格管理 - 列定义模型"""

from datetime import datetime, timezone
from typing import Dict, Any, List
from ..base_model import BaseModel

VALID_COLUMN_TYPES = {'text', 'number', 'select', 'tags', 'url', 'table_ref'}


class GotionColumnModel(BaseModel):
    """gotion 自定义表的列定义"""

    @classmethod
    def get_table_name(cls) -> str:
        return 'gotion_columns'

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id':         {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            'table_id':   {'type': 'INTEGER', 'not_null': True},
            'name':       {'type': 'TEXT',    'not_null': True},
            'key':        {'type': 'TEXT',    'not_null': True},
            'type':       {'type': 'TEXT',    'not_null': True, 'default': "'text'"},
            'config':     {'type': 'TEXT',    'not_null': False, 'default': None},  # JSON string
            'sort_order': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'is_title':   {'type': 'INTEGER', 'not_null': False, 'default': 0},     # 0/1
            'width':      {'type': 'INTEGER', 'not_null': False, 'default': 200},
            'created_at': {'type': 'TEXT',    'not_null': False, 'default': None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_gotion_columns_table', 'columns': ['table_id']},
            {'name': 'idx_gotion_columns_sort',  'columns': ['table_id', 'sort_order']},
        ]

    def save(self) -> bool:
        if not self._data.get('created_at'):
            self._data['created_at'] = datetime.now(timezone.utc).isoformat()
        return super().save()

    @classmethod
    def find_by_table(cls, table_id: int) -> List['GotionColumnModel']:
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
