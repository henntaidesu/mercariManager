# -*- coding: utf-8 -*-
"""库存出入库交易接口。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/transactions
- 完整 URL 示例: GET /mercariV2/src/use_web/transactions
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel
from typing import Optional
from ...db_manage.models.transaction import TransactionModel
from ...db_manage.models.inventory import InventoryModel

router = APIRouter()


class TransactionCreate(PydanticModel):
    type: str
    inventory_id: int
    warehouse_id: int
    target_warehouse_id: Optional[int] = None
    quantity: int
    remark: Optional[str] = None
    operator: Optional[str] = "管理员"


@router.get("")
def list_transactions(
    type: Optional[str] = None,
    inventory_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
):
    return TransactionModel.find_detail_list(
        tx_type=type,
        inventory_id=inventory_id,
        warehouse_id=warehouse_id,
        page=page,
        page_size=page_size,
    )


@router.post("")
def create_transaction(data: TransactionCreate):
    if data.type not in ("in", "out", "transfer"):
        raise HTTPException(status_code=400, detail="类型错误，仅支持 in/out/transfer")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于0")

    item = InventoryModel.find_by_id(id=data.inventory_id)
    if not item:
        raise HTTPException(status_code=404, detail="库存不存在")

    current_qty = item.quantity or 0

    if data.type == "in":
        item.quantity = current_qty + data.quantity
        item.save()
    elif data.type in ("out", "transfer"):
        if current_qty < data.quantity:
            raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
        item.quantity = current_qty - data.quantity
        item.save()

    tx = TransactionModel(
        type=data.type,
        inventory_id=data.inventory_id,
        warehouse_id=data.warehouse_id,
        target_warehouse_id=data.target_warehouse_id,
        quantity=data.quantity,
        remark=data.remark,
        operator=data.operator,
    )
    if not tx.save():
        raise HTTPException(status_code=500, detail="记录保存失败")

    result = TransactionModel.find_detail_list(page=1, page_size=1)
    items = result.get('items', [])
    return items[0] if items else tx.to_dict()
