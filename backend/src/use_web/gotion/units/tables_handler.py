# -*- coding: utf-8 -*-
"""Gotion 表格管理 - 表/列/行 CRUD 处理函数"""

import json
import re
from typing import Optional

from fastapi import HTTPException, Query

from src.db_manage.database import DatabaseManager
from src.db_manage.models import GotionTableModel, GotionColumnModel, GotionRowModel
from ..schemas import (
    TableCreate, TableUpdate, TableReorderRequest,
    ColumnCreate, ColumnUpdate, ColumnReorderRequest,
    RowCreate, RowUpdate,
)


def _slug(text: str) -> str:
    """将文字转为安全的 key（保留字母/数字/中文/日文，去除空格）"""
    return re.sub(r'[^\w\u3000-\u9fff\u4e00-\u9fff\u3040-\u30ff]', '_', text).strip('_') or 'col'


def _col_to_dict(col: GotionColumnModel) -> dict:
    d = col.to_dict()
    d['is_title'] = bool(d.get('is_title'))
    if d.get('config'):
        try:
            d['config'] = json.loads(d['config'])
        except Exception:
            d['config'] = {}
    else:
        d['config'] = {}
    return d


def _table_to_dict_with_children(t: GotionTableModel) -> dict:
    """将表转换为字典，包含子表列表"""
    d = t.to_dict()
    children = GotionTableModel.find_children(t.id)
    d['children'] = [_table_basic(c) for c in children]
    return d


def _table_basic(t: GotionTableModel) -> dict:
    """基础表信息"""
    return {
        'id': t.id,
        'name': t.name,
        'icon': t.icon,
        'description': t.description,
        'parent_id': t.parent_id,
        'sort_order': t.sort_order,
        'created_at': t.created_at,
        'updated_at': t.updated_at,
    }


def _assert_no_cycle(table_id: int, new_parent_id: int):
    """沿祖先链向上检查，禁止把表移到自己或自己的后代下面（防止成环导致递归删除死循环、表从侧栏消失）"""
    current = new_parent_id
    seen = set()
    while current is not None:
        if current == table_id or current in seen:
            raise HTTPException(400, '不能将表移动到自己或其子表之下')
        seen.add(current)
        parent = GotionTableModel.find_by_id(id=current)
        current = parent.parent_id if parent else None


# ═══════════════════════════════════════════════════════════
#   TABLES
# ═══════════════════════════════════════════════════════════

def list_tables():
    """获取所有顶级表（含子表列表）"""
    top_tables = GotionTableModel.find_top_level()
    return [_table_to_dict_with_children(t) for t in top_tables]


def create_table(body: TableCreate):
    # 验证父表存在（如果指定了）
    if body.parent_id is not None:
        parent = GotionTableModel.find_by_id(id=body.parent_id)
        if not parent:
            raise HTTPException(404, '父表不存在')

    with DatabaseManager().transaction():
        t = GotionTableModel(
            name=body.name,
            icon=body.icon,
            description=body.description,
            parent_id=body.parent_id,
            sort_order=GotionTableModel.get_next_sort_order(body.parent_id),
        )
        if not t.save():
            raise HTTPException(500, '创建表失败')

        # 自动创建第一个"名称"列
        col = GotionColumnModel(
            table_id=t.id,
            name='名称',
            key='name',
            type='text',
            sort_order=0,
            width=240,
        )
        if not col.save():
            raise HTTPException(500, '创建默认列失败')
    return _table_to_dict_with_children(t)


def get_table(table_id: int):
    t = GotionTableModel.find_by_id(id=table_id)
    if not t:
        raise HTTPException(404, '表不存在')
    d = _table_to_dict_with_children(t)
    d['columns'] = [_col_to_dict(c) for c in GotionColumnModel.find_by_table(table_id)]
    return d


def update_table(table_id: int, body: TableUpdate):
    t = GotionTableModel.find_by_id(id=table_id)
    if not t:
        raise HTTPException(404, '表不存在')
    fields = body.model_fields_set  # 区分"未提供"与"显式传 null"
    if 'name' in fields and body.name is not None:
        t._data['name'] = body.name
    if 'icon' in fields:
        t._data['icon'] = body.icon or None
    if 'description' in fields:
        t._data['description'] = body.description or None
    if 'parent_id' in fields and body.parent_id != t._data.get('parent_id'):
        if body.parent_id is not None:
            if not GotionTableModel.find_by_id(id=body.parent_id):
                raise HTTPException(404, '父表不存在')
            _assert_no_cycle(table_id, body.parent_id)
        # parent_id 为 None 表示移回顶级
        t._data['parent_id'] = body.parent_id
        t._data['sort_order'] = GotionTableModel.get_next_sort_order(body.parent_id)
    if not t.save():
        raise HTTPException(500, '更新失败')
    return _table_to_dict_with_children(t)


def delete_table(table_id: int):
    t = GotionTableModel.find_by_id(id=table_id)
    if not t:
        raise HTTPException(404, '表不存在')
    # 整棵子树在一个事务里删除，失败全部回滚
    with DatabaseManager().transaction():
        _delete_table_recursive(table_id, set())


def _delete_table_recursive(table_id: int, visited: set):
    """递归删除表及其所有子表；visited 防御历史数据中已存在的环"""
    if table_id in visited:
        return
    visited.add(table_id)
    for child in GotionTableModel.find_children(table_id):
        _delete_table_recursive(child.id, visited)
    # 删除当前表的列和行
    GotionColumnModel.delete_all('[table_id] = ?', (table_id,))
    GotionRowModel.delete_all('[table_id] = ?', (table_id,))
    t = GotionTableModel.find_by_id(id=table_id)
    if t and not t.delete():
        raise HTTPException(500, f'删除表 {table_id} 失败')


def reorder_tables(body: TableReorderRequest):
    with DatabaseManager().transaction():
        for item in body.items:
            t = GotionTableModel.find_by_id(id=item.id)
            if t and t._data.get('sort_order') != item.sort_order:
                t._data['sort_order'] = item.sort_order
                if not t.save():
                    raise HTTPException(500, '排序保存失败')
    return {'ok': True}


# ═══════════════════════════════════════════════════════════
#   COLUMNS
# ═══════════════════════════════════════════════════════════

def list_columns(table_id: int):
    return [_col_to_dict(c) for c in GotionColumnModel.find_by_table(table_id)]


def create_column(table_id: int, body: ColumnCreate):
    if not GotionTableModel.find_by_id(id=table_id):
        raise HTTPException(404, '表不存在')

    key = _slug(body.name)
    existing_keys = {c.key for c in GotionColumnModel.find_by_table(table_id)}
    base_key, i = key, 1
    while key in existing_keys:
        key = f'{base_key}_{i}'
        i += 1

    config_str = json.dumps(body.config, ensure_ascii=False) if body.config else None
    col = GotionColumnModel(
        table_id=table_id,
        name=body.name,
        key=key,
        type=body.type,
        config=config_str,
        sort_order=GotionColumnModel.get_next_sort_order(table_id),
        width=body.width,
    )
    if not col.save():
        raise HTTPException(500, '创建列失败')
    return _col_to_dict(col)


def update_column(table_id: int, col_id: int, body: ColumnUpdate):
    col = GotionColumnModel.find_by_id(id=col_id)
    if not col or col.table_id != table_id:
        raise HTTPException(404, '列不存在')

    if body.name is not None:
        col._data['name'] = body.name
    if body.type is not None:
        col._data['type'] = body.type
    if body.config is not None:
        col._data['config'] = json.dumps(body.config, ensure_ascii=False)

    if body.width is not None:
        col._data['width'] = body.width
    if body.sort_order is not None:
        col._data['sort_order'] = body.sort_order

    if not col.save():
        raise HTTPException(500, '更新列失败')
    return _col_to_dict(col)


def delete_column(table_id: int, col_id: int):
    col = GotionColumnModel.find_by_id(id=col_id)
    if not col or col.table_id != table_id:
        raise HTTPException(404, '列不存在')
    if not col.delete():
        raise HTTPException(500, '删除列失败')


def reorder_columns(table_id: int, body: ColumnReorderRequest):
    with DatabaseManager().transaction():
        for item in body.items:
            col = GotionColumnModel.find_by_id(id=item.id)
            if col and col.table_id == table_id and col._data.get('sort_order') != item.sort_order:
                col._data['sort_order'] = item.sort_order
                if not col.save():
                    raise HTTPException(500, '排序保存失败')
    return {'ok': True}


# ═══════════════════════════════════════════════════════════
#   ROWS
# ═══════════════════════════════════════════════════════════

def list_rows(
    table_id: int,
    filter_col: Optional[str] = Query(None),
    filter_val: Optional[str] = Query(None),
):
    if filter_col and filter_val is not None:
        rows = GotionRowModel.find_by_table_filtered(table_id, filter_col, filter_val)
    else:
        rows = GotionRowModel.find_by_table(table_id)
    return [r.to_dict() for r in rows]


def create_row(table_id: int, body: RowCreate):
    if not GotionTableModel.find_by_id(id=table_id):
        raise HTTPException(404, '表不存在')
    row = GotionRowModel(
        table_id=table_id,
        data=body.data,
        sort_order=GotionRowModel.get_next_sort_order(table_id),
    )
    if not row.save():
        raise HTTPException(500, '创建行失败')
    return row.to_dict()


def update_row(table_id: int, row_id: int, body: RowUpdate):
    row = GotionRowModel.find_by_id(id=row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(404, '行不存在')
    row._data['data'] = body.data
    if not row.save():
        raise HTTPException(500, '更新行失败')
    return row.to_dict()


def delete_row(table_id: int, row_id: int):
    row = GotionRowModel.find_by_id(id=row_id)
    if not row or row.table_id != table_id:
        raise HTTPException(404, '行不存在')
    if not row.delete():
        raise HTTPException(500, '删除行失败')
