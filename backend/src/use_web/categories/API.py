# -*- coding: utf-8 -*-
"""分类管理接口。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/categories
- 完整 URL 示例: GET /mercariV2/src/use_web/categories
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel
from typing import Optional
from ...db_manage.models.category import CategoryModel

router = APIRouter()


class CategoryCreate(PydanticModel):
    name: str
    description: Optional[str] = None


class CategoryUpdate(PydanticModel):
    name: Optional[str] = None
    description: Optional[str] = None


def _serialize(cat: CategoryModel) -> dict:
    d = cat.to_dict()
    d['inventory_count'] = CategoryModel.get_inventory_count(cat.id)
    return d


@router.get("")
def list_categories():
    return [_serialize(c) for c in CategoryModel.find_all(order_by="id ASC")]


@router.post("")
def create_category(data: CategoryCreate):
    if CategoryModel.find_by_name(data.name):
        raise HTTPException(status_code=400, detail="分类名称已存在")
    cat = CategoryModel(name=data.name, description=data.description)
    if not cat.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(cat)


@router.put("/{cid}")
def update_category(cid: int, data: CategoryUpdate):
    cat = CategoryModel.find_by_id(id=cid)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if data.name is not None:
        cat.name = data.name
    if data.description is not None:
        cat.description = data.description
    cat.save()
    return _serialize(cat)


@router.delete("/{cid}")
def delete_category(cid: int):
    cat = CategoryModel.find_by_id(id=cid)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if CategoryModel.get_inventory_count(cid) > 0:
        raise HTTPException(status_code=400, detail="该分类下存在商品，无法删除")
    cat.delete()
    return {"message": "删除成功"}
