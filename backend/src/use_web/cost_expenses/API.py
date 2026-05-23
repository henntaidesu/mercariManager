# -*- coding: utf-8 -*-
"""成本支出（包材/快递费）管理 API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/cost_expenses
- 完整 URL 示例: GET /mercariV2/src/use_web/cost_expenses/
"""
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel

from ...db_manage.models.cost_expense import CostExpenseModel
from ...db_manage.models.cost_record import CostRecordModel
from ...db_manage.models.order import OrderModel
from ...order_goods_ratio import owner_weights_from_order_goods_ratio

router = APIRouter()
ALLOWED_TYPES = {"快递费", "包装材料"}


class CostExpenseCreate(PydanticModel):
    type: Optional[str] = None
    item_name: str
    quantity: int
    unit_price: int
    owner: Optional[str] = None
    order_no: Optional[str] = None
    record_time: Optional[int] = None


class CostExpenseUpdate(PydanticModel):
    type: Optional[str] = None
    item_name: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[int] = None
    owner: Optional[str] = None
    order_no: Optional[str] = None
    record_time: Optional[int] = None


def _validate_required_text(value: Optional[str], field_name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    return cleaned


def _validate_positive_int(value: Optional[int], field_name: str) -> int:
    if value is None or int(value) <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name}必须大于0")
    return int(value)


def _validate_type(value: Optional[str]) -> str:
    cost_type = _validate_required_text(value, "类型")
    if cost_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="类型仅支持：快递费、包装材料")
    return cost_type


def _default_london_ts() -> int:
    return int(datetime.now(ZoneInfo("Europe/London")).timestamp())


def _find_packaging_item_latest(item_name: str):
    rows = CostRecordModel.find_all(
        where="type = ? AND item_name = ?",
        params=("packaging", item_name),
        order_by="cost_date DESC, id DESC",
        limit=1,
    )
    return rows[0] if rows else None


def _validate_packaging_stock(item_name: str, quantity: int):
    source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    stock_qty = int(source.quantity or 0)
    if stock_qty < quantity:
        raise HTTPException(status_code=400, detail=f"库存包材数量不足，当前仅剩 {stock_qty}")


def _sync_expense_type_from_source(item_name: str) -> str:
    source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    source_type = (source.type or "").strip()
    if source_type == "packaging":
        return "包装材料"
    if source_type == "shipping":
        return "快递费"
    # 库存包材模块目前只允许包装类；这里做兜底保护
    raise HTTPException(status_code=400, detail="该物品在库存包材中的类型不支持同步")


def _normalize_order_no(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned or None


def _ensure_order_exists(order_no: Optional[str]) -> Optional[str]:
    normalized = _normalize_order_no(order_no)
    if not normalized:
        return None
    rows = OrderModel.find_all(where="[order_no] = ?", params=(normalized,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="关联订单不存在")
    return normalized


def _apply_order_net_income_cost(order_no: Optional[str], expense_total: int):
    normalized = _normalize_order_no(order_no)
    if not normalized or expense_total <= 0:
        return
    rows = OrderModel.find_all(where="[order_no] = ?", params=(normalized,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="关联订单不存在")
    order = rows[0]
    current = int(order.net_income or 0)
    order.net_income = current - int(expense_total)
    if not order.save():
        raise HTTPException(status_code=500, detail="更新订单净收益失败")


def total_packaging_expense_yen_for_order(order_no: Optional[str]) -> int:
    """本订单已保存的「包装材料」支出合计（日元整数）。"""
    ono = _normalize_order_no(order_no)
    if not ono:
        return 0
    rows = CostExpenseModel().db.execute_query(
        """
        SELECT COALESCE(SUM(COALESCE([quantity], 0) * COALESCE([unit_price], 0)), 0)
        FROM [cost_expenses]
        WHERE [order_no] = ? AND [type] = ?
        """,
        (ono, "包装材料"),
    )
    if not rows:
        return 0
    try:
        return max(0, int(rows[0][0] or 0))
    except (TypeError, ValueError):
        return 0


def deduct_packaging_total_from_order_net_income(order) -> None:
    """
    煤炉回填的 net_income 为「售价−手续费−运费」；再减去本订单包材合计，
    与新增包材时累计扣减一致。订单页「刷新」会覆盖 net_income，须在此处重算包材扣减。
    """
    if order is None:
        return
    base = getattr(order, "net_income", None)
    if base is None:
        return
    total = total_packaging_expense_yen_for_order(getattr(order, "order_no", None))
    if total <= 0:
        return
    order.net_income = int(base) - int(total)


def _resolve_order_owner_value_weights(order_no: str):
    """
    根据订单解析「归属人 -> 权重」用于包材分摊：
    1) 与订单二级表一致：组合标题 + 在售原价权重 → 比例价格，按归属汇总（货物比例）；
    2) 否则：inventory.price * 件数；
    3) 再否则：按件数均分权重。
    """
    ono = (order_no or "").strip()
    if not ono:
        return []
    ratio_weights = owner_weights_from_order_goods_ratio(ono)
    if ratio_weights:
        return ratio_weights
    rows = CostExpenseModel().db.execute_query(
        """
        SELECT
            COALESCE(
                NULLIF(TRIM(u.[display_name]), ''),
                NULLIF(TRIM(u.[username]), ''),
                ''
            ) AS owner_key,
            COALESCE(p.[price], 0) AS product_price,
            COALESCE(l.[quantity], 1) AS line_qty
        FROM [order_outbound_lines] l
        LEFT JOIN [inventory] p ON p.[id] = l.[inventory_id]
        LEFT JOIN [users] u ON u.[id] = p.[owner_user_id]
        WHERE l.[order_no] = ?
          AND l.[inventory_id] IS NOT NULL
        """,
        (ono,),
    )
    grouped_price_weight = {}
    grouped_qty_weight = {}
    for owner_raw, price_raw, qty_raw in rows:
        owner = str(owner_raw or "").strip()
        if not owner:
            continue
        try:
            price = int(price_raw or 0)
        except (TypeError, ValueError):
            price = 0
        try:
            qty = int(qty_raw or 1)
        except (TypeError, ValueError):
            qty = 1
        safe_qty = max(1, qty)
        grouped_qty_weight[owner] = int(grouped_qty_weight.get(owner, 0)) + int(safe_qty)
        price_weight = max(0, price) * safe_qty
        grouped_price_weight[owner] = int(grouped_price_weight.get(owner, 0)) + int(price_weight)

    # 优先按商品价值（price * qty）；若订单内价格缺失/为0导致总权重为0，则回退按数量分配。
    sum_price_weight = sum(int(v) for v in grouped_price_weight.values())
    if sum_price_weight > 0:
        return [
            {"owner": k, "weight": int(v)}
            for k, v in grouped_price_weight.items()
            if int(v) > 0
        ]
    return [
        {"owner": k, "weight": int(v)}
        for k, v in grouped_qty_weight.items()
        if int(v) > 0
    ]


def _split_int_by_weights(total: int, owner_weights):
    """
    按权重把整数总量拆分到多人（结果均为整数，且总和严格等于 total）。
    采用最大余数法分配尾差。
    """
    amount = int(total or 0)
    if amount <= 0 or not owner_weights:
        return []
    sum_w = sum(int(it.get("weight") or 0) for it in owner_weights)
    if sum_w <= 0:
        return []
    floors = []
    fracs = []
    for it in owner_weights:
        w = int(it.get("weight") or 0)
        raw = amount * (float(w) / float(sum_w))
        f = int(raw)
        floors.append(f)
        fracs.append(raw - f)
    remain = amount - sum(floors)
    alloc = floors[:]
    if remain > 0:
        idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
        for i in idxs[:remain]:
            alloc[i] += 1
    out = []
    for i, it in enumerate(owner_weights):
        share = int(alloc[i] or 0)
        if share <= 0:
            continue
        out.append({"owner": str(it.get("owner") or "").strip(), "share": share})
    return out


@router.get("")
def list_cost_expenses(
    type: Optional[str] = None,
    owner: Optional[str] = None,
    order_no: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
):
    where_parts = ["1=1"]
    params = []
    if type:
        if type.strip() not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="类型仅支持：快递费、包装材料")
        where_parts.append("[type] = ?")
        params.append(type.strip())
    if owner:
        where_parts.append("[owner] = ?")
        params.append(owner.strip())
    if order_no:
        where_parts.append("[order_no] = ?")
        params.append(order_no.strip())
    if start_time is not None:
        where_parts.append("[record_time] >= ?")
        params.append(int(start_time))
    if end_time is not None:
        where_parts.append("[record_time] <= ?")
        params.append(int(end_time))

    where_clause = " AND ".join(where_parts)
    total = CostExpenseModel.count(where=where_clause, params=tuple(params))
    rows = CostExpenseModel.find_all(
        where=where_clause,
        params=tuple(params),
        order_by="record_time DESC, id DESC",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [row.to_dict() for row in rows],
    }


@router.post("")
def create_cost_expense(data: CostExpenseCreate):
    item_name = _validate_required_text(data.item_name, "物品名称")
    expense_quantity = _validate_positive_int(data.quantity, "数量")
    _validate_packaging_stock(item_name, expense_quantity)
    source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    source_original_quantity = int(source.quantity or 0)
    synced_type = _sync_expense_type_from_source(item_name)
    bound_order_no = _ensure_order_exists(data.order_no)
    unit_price = _validate_positive_int(data.unit_price, "单价")
    expense_total = int(expense_quantity) * int(unit_price)
    record_time = int(data.record_time) if data.record_time is not None else _default_london_ts()
    owner_rows = []
    if bound_order_no:
        owner_weights = _resolve_order_owner_value_weights(bound_order_no)
        if len(owner_weights) > 1:
            # 包材件数为整数时，按「件数」无法在多人之间公平拆分（例如仅 1 件会整件判给一人）。
            # 多人归属时改为按「总成本 expense_total」日元比例拆成多行：
            # 每行 quantity=1，unit_price=该人分摊金额（行金额之和仍等于原总价）。
            amt_split_rows = _split_int_by_weights(expense_total, owner_weights)
            owner_rows = [
                {
                    "owner": str(it.get("owner") or "").strip() or None,
                    "quantity": 1,
                    "unit_price": int(it.get("share") or 0),
                }
                for it in amt_split_rows
                if int(it.get("share") or 0) > 0
            ]
        elif len(owner_weights) == 1:
            owner_rows = [{
                "owner": str(owner_weights[0].get("owner") or "").strip() or None,
                "quantity": expense_quantity,
                "unit_price": unit_price,
            }]
    if not owner_rows:
        owner_rows = [{
            "owner": (data.owner or "").strip() or None,
            "quantity": expense_quantity,
            "unit_price": unit_price,
        }]

    created_rows = []
    source.quantity = source_original_quantity - expense_quantity
    if not source.save():
        raise HTTPException(status_code=500, detail="自动扣减库存包材失败")
    try:
        for owner_item in owner_rows:
            share_qty = int(owner_item.get("quantity") or 0)
            line_unit = int(owner_item.get("unit_price") if owner_item.get("unit_price") is not None else unit_price)
            if share_qty <= 0 or line_unit <= 0:
                continue
            row = CostExpenseModel(
                type=synced_type,
                item_name=item_name,
                quantity=share_qty,
                unit_price=line_unit,
                owner=owner_item.get("owner"),
                order_no=bound_order_no,
                record_time=record_time,
            )
            if not row.save():
                raise HTTPException(status_code=500, detail="保存失败")
            created_rows.append(row)
    except Exception:
        for obj in created_rows:
            try:
                obj.delete()
            except Exception:
                pass
        source.quantity = source_original_quantity
        source.save()
        raise
    if bound_order_no and synced_type == "包装材料":
        order_rows = OrderModel.find_all(
            where="[order_no] = ?", params=(bound_order_no,), limit=1
        )
        if order_rows:
            order_rows[0].packaging_waived = 0
            order_rows[0].save()

    try:
        _apply_order_net_income_cost(bound_order_no, expense_total)
    except Exception:
        for obj in created_rows:
            try:
                obj.delete()
            except Exception:
                pass
        source.quantity = source_original_quantity
        source.save()
        raise
    if len(created_rows) == 1:
        return created_rows[0].to_dict()
    return {
        "split_count": len(created_rows),
        "items": [r.to_dict() for r in created_rows],
    }


@router.put("/{cid}")
def update_cost_expense(cid: int, data: CostExpenseUpdate):
    row = CostExpenseModel.find_by_id(id=cid)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    next_item_name = _validate_required_text(
        data.item_name if data.item_name is not None else row.item_name,
        "物品名称",
    )
    next_quantity = _validate_positive_int(
        data.quantity if data.quantity is not None else row.quantity,
        "数量",
    )
    _validate_packaging_stock(next_item_name, next_quantity)
    next_synced_type = _sync_expense_type_from_source(next_item_name)

    row.type = next_synced_type
    if data.item_name is not None:
        row.item_name = _validate_required_text(data.item_name, "物品名称")
    if data.quantity is not None:
        row.quantity = _validate_positive_int(data.quantity, "数量")
    if data.unit_price is not None:
        row.unit_price = _validate_positive_int(data.unit_price, "单价")
    if data.owner is not None:
        row.owner = data.owner.strip() or None
    if data.record_time is not None:
        row.record_time = int(data.record_time)

    if not row.save():
        raise HTTPException(status_code=500, detail="更新失败")
    return row.to_dict()


@router.delete("/{cid}")
def delete_cost_expense(cid: int):
    row = CostExpenseModel.find_by_id(id=cid)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    if not row.delete():
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": "删除成功"}
