# -*- coding: utf-8 -*-
"""游戏/商品类型管理接口。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/product_types
- 完整 URL 示例: GET /mercariV2/src/use_web/product_types
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel
from typing import Optional
from ...db_manage.models.product_type import ProductTypeModel

router = APIRouter()


class ProductTypeCreate(PydanticModel):
    name: str
    description: Optional[str] = None


class ProductTypeUpdate(PydanticModel):
    name: Optional[str] = None
    description: Optional[str] = None


def _serialize(game_type: ProductTypeModel) -> dict:
    d = game_type.to_dict()
    d['inventory_count'] = ProductTypeModel.get_inventory_count(game_type.id)
    return d


@router.get("")
def list_product_types():
    return [_serialize(t) for t in ProductTypeModel.find_all(order_by="id ASC")]


@router.post("")
def create_product_type(data: ProductTypeCreate):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="游戏类型名称不能为空")
    if ProductTypeModel.find_by_name(name):
        raise HTTPException(status_code=400, detail="游戏类型名称已存在")
    game_type = ProductTypeModel(name=name, description=data.description)
    if not game_type.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(game_type)


@router.put("/{type_id}")
def update_product_type(type_id: int, data: ProductTypeUpdate):
    game_type = ProductTypeModel.find_by_id(id=type_id)
    if not game_type:
        raise HTTPException(status_code=404, detail="游戏类型不存在")
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="游戏类型名称不能为空")
        exists = ProductTypeModel.find_by_name(name)
        if exists and exists.id != type_id:
            raise HTTPException(status_code=400, detail="游戏类型名称已存在")
        game_type.name = name
    if data.description is not None:
        game_type.description = data.description
    game_type.save()
    return _serialize(game_type)


@router.delete("/{type_id}")
def delete_product_type(type_id: int):
    game_type = ProductTypeModel.find_by_id(id=type_id)
    if not game_type:
        raise HTTPException(status_code=404, detail="游戏类型不存在")
    if ProductTypeModel.get_inventory_count(type_id) > 0:
        raise HTTPException(status_code=400, detail="该游戏类型下存在商品，无法删除")
    game_type.delete()
    return {"message": "删除成功"}
