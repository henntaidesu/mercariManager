# -*- coding: utf-8 -*-
"""Gotion 表格管理 - 表元数据模型

用户自定义表（Notion 风格多维表格）的元数据，支持父子两级层级。
"""

from datetime import datetime, timezone
from typing import Dict, Any, List
from ..base_model import BaseModel


class GotionTableModel(BaseModel):
    """gotion 自定义表元数据（支持父子层级）"""

    @classmethod
    def get_table_name(cls) -> str:
        return 'gotion_tables'

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id':          {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            'name':        {'type': 'TEXT',    'not_null': True},
            'icon':        {'type': 'TEXT',    'not_null': False, 'default': None},
            'description': {'type': 'TEXT',    'not_null': False, 'default': None},
            'parent_id':   {'type': 'INTEGER', 'not_null': False, 'default': None},  # 父表ID，None表示顶级表
            'sort_order':  {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'created_at':  {'type': 'TEXT',    'not_null': False, 'default': None},
            'updated_at':  {'type': 'TEXT',    'not_null': False, 'default': None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_gotion_tables_sort',   'columns': ['sort_order']},
            {'name': 'idx_gotion_tables_parent', 'columns': ['parent_id']},
        ]

    def save(self) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        if not self._data.get('created_at'):
            self._data['created_at'] = now
        self._data['updated_at'] = now
        return super().save()

    @classmethod
    def get_next_sort_order(cls, parent_id=None) -> int:
        db = cls().db
        if parent_id is None:
            result = db.execute_query(
                f"SELECT MAX(sort_order) FROM [{cls.get_table_name()}] WHERE parent_id IS NULL"
            )
        else:
            result = db.execute_query(
                f"SELECT MAX(sort_order) FROM [{cls.get_table_name()}] WHERE parent_id = ?",
                (parent_id,)
            )
        max_order = result[0][0] if result and result[0][0] is not None else -1
        return max_order + 1

    @classmethod
    def find_children(cls, parent_id: int) -> List['GotionTableModel']:
        """获取指定父表的所有子表"""
        return cls.find_all(
            where='[parent_id] = ?',
            params=(parent_id,),
            order_by='[sort_order] ASC, [id] ASC'
        )

    @classmethod
    def find_top_level(cls) -> List['GotionTableModel']:
        """获取所有顶级表（无父表）"""
        return cls.find_all(
            where='[parent_id] IS NULL',
            order_by='[sort_order] ASC, [id] ASC'
        )
