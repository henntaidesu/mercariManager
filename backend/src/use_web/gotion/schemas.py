# -*- coding: utf-8 -*-
"""Gotion 表格管理 - Pydantic 请求模型"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, field_validator


# ── Table ────────────────────────────────────────────────
class TableCreate(BaseModel):
    name: str
    icon: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None  # 父表ID，None表示顶级表

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, v):
        if not v or not v.strip():
            raise ValueError('表名不能为空')
        return v.strip()

class TableUpdate(BaseModel):
    # parent_id 显式传 null 表示移到顶级；不传表示不修改（通过 model_fields_set 区分）
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError('表名不能为空')
        return v.strip() if v is not None else v

class TableReorderItem(BaseModel):
    id: int
    sort_order: int

class TableReorderRequest(BaseModel):
    items: List[TableReorderItem]


# ── Column ───────────────────────────────────────────────
VALID_COL_TYPES = {'text', 'number', 'select', 'tags', 'url', 'table_ref'}

class ColumnCreate(BaseModel):
    name: str
    type: str = 'text'
    config: Optional[Dict[str, Any]] = None
    width: int = 200

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if v not in VALID_COL_TYPES:
            raise ValueError(f"列类型必须是 {VALID_COL_TYPES} 之一")
        return v

class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    width: Optional[int] = None
    sort_order: Optional[int] = None

    @field_validator('type')
    @classmethod
    def validate_type(cls, v):
        if v is not None and v not in VALID_COL_TYPES:
            raise ValueError(f"列类型必须是 {VALID_COL_TYPES} 之一")
        return v

class ColumnReorderItem(BaseModel):
    id: int
    sort_order: int

class ColumnReorderRequest(BaseModel):
    items: List[ColumnReorderItem]


# ── Row ──────────────────────────────────────────────────
class RowCreate(BaseModel):
    data: Dict[str, Any] = {}

class RowUpdate(BaseModel):
    data: Dict[str, Any]
