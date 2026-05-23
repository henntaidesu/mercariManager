# -*- coding: utf-8 -*-
"""订单管理 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/orders
- 完整 URL 示例: GET /mercariV2/src/use_web/orders/stats
"""
import json
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel
from typing import List, Optional
from ...db_manage.database import DatabaseManager
from ...db_manage.models.order import OrderModel
from ...db_manage.models.order_outbound_line import OrderOutboundLineModel
from ...web_drive.account_serial_queue import queue_key_for_meilu_account, run_meilu_serial_async
from ...operation_mercari.sync_data import resolve_account_id_by_seller_id
from ...operation_mercari.get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ...operation_mercari.get_order.description_mgmt_ids import (
    refresh_inventory_pending_outbound_qty,
    sync_outbound_lines_for_order,
)
from ...order_goods_ratio import apply_bundle_title_ratio_pricing

router = APIRouter()
db = DatabaseManager()

# 订单 status 仅使用煤炉侧取值（与 items 列表 / 取引详情一致）
ORDER_STATUSES = frozenset(
    {
        "pending",
        "trading",
        "wait_payment",
        "wait_shipping",
        "wait_review",
        "done",
        "sold_out",
        "cancelled",
        "cancel_request",
    }
)
ALL_ORDER_STATUSES = ORDER_STATUSES


def _encode_thumbnails(urls: Optional[List[str]]) -> Optional[str]:
    if not urls:
        return None
    out = [str(u).strip() for u in urls if u is not None and str(u).strip()]
    return json.dumps(out, ensure_ascii=False) if out else None


class OrderCreate(PydanticModel):
    order_no: str
    order_date: int
    order_updated_at: Optional[int] = None
    purchase_time: Optional[int] = None
    customer_name: Optional[str] = None
    data_user: Optional[str] = None
    status: str = "pending"
    amount: int
    service_fee: Optional[int] = None
    net_income: Optional[int] = None
    carrier_display_name: Optional[str] = None
    request_class_display_name: Optional[str] = None
    shipping_fee: Optional[int] = None
    tracking_no: Optional[str] = None
    transaction_evidence_id: Optional[int] = None
    remark: Optional[str] = None
    description: Optional[str] = None
    thumbnails: Optional[List[str]] = None


class RefreshOrderInfoBody(PydanticModel):
    """单行刷新：transaction_evidences/get 回填，需指定卖家 ID 以选择对应煤炉账号。"""

    order_no: str
    data_user: str


class OrderPackagingWaiveBody(PydanticModel):
    order_no: str


class OrderUpdate(PydanticModel):
    order_no: Optional[str] = None
    order_date: Optional[int] = None
    order_updated_at: Optional[int] = None
    purchase_time: Optional[int] = None
    customer_name: Optional[str] = None
    data_user: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[int] = None
    service_fee: Optional[int] = None
    net_income: Optional[int] = None
    carrier_display_name: Optional[str] = None
    request_class_display_name: Optional[str] = None
    shipping_fee: Optional[int] = None
    tracking_no: Optional[str] = None
    transaction_evidence_id: Optional[int] = None
    remark: Optional[str] = None
    description: Optional[str] = None
    thumbnails: Optional[List[str]] = None


class OutboundStockOutBody(PydanticModel):
    remark: Optional[str] = None


class OutboundLineBindInventoryBody(PydanticModel):
    """将未匹配到库存的出库明细行手动关联到某条库存（仅允许 inventory_id 为空时）。"""

    inventory_id: int
    quantity: Optional[int] = None


class ManualOutboundLineCreateBody(PydanticModel):
    order_no: str
    inventory_id: int
    quantity: int = 1
    management_id: Optional[str] = None
    remark: Optional[str] = None


class ManualOutboundLineItem(PydanticModel):
    inventory_id: int
    quantity: int = 1
    management_id: Optional[str] = None


class ManualOutboundLinesBatchCreateBody(PydanticModel):
    order_no: str
    lines: List[ManualOutboundLineItem]
    remark: Optional[str] = None


def _validate_status_query(status: Optional[str]) -> None:
    """列表/统计筛选：仅允许煤炉订单状态。"""
    if status is None or not str(status).strip():
        return
    s = str(status).strip()
    if s not in ALL_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="订单状态错误")


def _validate_order_status(status: str):
    if status not in ALL_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="订单状态错误")


def _normalize_order_no(order_no: str) -> str:
    val = (order_no or "").strip()
    if not val:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    return val


def _inventory_ids_for_order(order_no: str) -> List[int]:
    rows = db.execute_query(
        """
        SELECT DISTINCT [inventory_id]
        FROM [order_outbound_lines]
        WHERE [order_no] = ? AND [inventory_id] IS NOT NULL
        """,
        ((order_no or "").strip(),),
    )
    out: List[int] = []
    for (raw_id,) in rows:
        try:
            n = int(raw_id)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return out


@router.get("/stats")
def order_stats(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    today_start_ts: Optional[int] = None,
    today_end_ts: Optional[int] = None,
):
    """当前筛选条件下的全表汇总（金额、手续费、快递费、净收益及行数），不受分页影响。

    已取消（cancelled）订单不计入本接口汇总；列表仍可按状态筛选查看。
    筛选时间区间：start_ts / end_ts 为 Unix 秒（与列表一致），按
    COALESCE(order_updated_at, purchase_time, order_date)（最后更新优先，缺省回退购入/下单）比较；
    建议由前端按本地自然日 0 点～当日结束换算。
    可选 today_start_ts / today_end_ts（同为 Unix 秒，本地「今天」起止）：在相同 keyword、status 下汇总「今日」
    （同上时间口径），不受 start_ts/end_ts 影响。

    sum_packaging / today_sum_packaging：关联订单的「包装材料」支出合计（日元），筛选条件与上述一致。
    """
    _validate_status_query(status)
    out = OrderModel.aggregate_sums(
        keyword=keyword,
        status=status,
        start_ts=start_ts,
        end_ts=end_ts,
        owner_user_id=owner_user_id,
    )
    out["sum_packaging"] = OrderModel.aggregate_packaging_expense_yen(
        keyword=keyword,
        status=status,
        start_ts=start_ts,
        end_ts=end_ts,
        owner_user_id=owner_user_id,
    )
    if today_start_ts is not None and today_end_ts is not None:
        t = OrderModel.aggregate_sums(
            keyword=keyword,
            status=status,
            start_ts=int(today_start_ts),
            end_ts=int(today_end_ts),
            owner_user_id=owner_user_id,
        )
        out["today_total_count"] = t["total_count"]
        out["today_sum_amount"] = t["sum_amount"]
        out["today_sum_service_fee"] = t["sum_service_fee"]
        out["today_sum_shipping_fee"] = t["sum_shipping_fee"]
        out["today_sum_net_income"] = t["sum_net_income"]
        out["today_sum_packaging"] = OrderModel.aggregate_packaging_expense_yen(
            keyword=keyword,
            status=status,
            start_ts=int(today_start_ts),
            end_ts=int(today_end_ts),
            owner_user_id=owner_user_id,
        )
    return out


@router.get("/outbound-lines")
def list_order_outbound_lines(
    order_no: str,
    owner_user_id: Optional[int] = None,
):
    """某订单从商品说明解析出的待出库明细（管理 ID、库存名称、仓库位置等）；比例价格优先组合标题在售价，否则按库存原价×件数（含手动添加）。"""
    ono = (order_no or "").strip()
    if not ono:
        raise HTTPException(status_code=400, detail="order_no 不能为空")
    # 先取全量明细再算 bundle 比例（与订单金额一致）；按归属筛选时不得只拿子集算权重
    all_items = OrderOutboundLineModel.list_enriched_for_order(ono)
    order_rows = db.execute_query(
        "SELECT COALESCE([amount], 0) FROM [orders] WHERE [order_no] = ? LIMIT 1",
        (ono,),
    )
    order_amount = int(order_rows[0][0] or 0) if order_rows else 0
    apply_bundle_title_ratio_pricing(all_items, order_amount)

    if owner_user_id is not None and int(owner_user_id) > 0:
        oid = int(owner_user_id)
        items = [
            it
            for it in all_items
            if it.get("inventory_id") is not None
            and int(
                it.get("product_owner_user_id")
                or it.get("inventory_owner_user_id")
                or 0
            )
            == oid
        ]
    else:
        items = all_items

    OrderOutboundLineModel.sort_owner_unmatched_first(items)
    return {"order_no": ono, "items": items}


def _outbound_line_has_inventory_id(line: OrderOutboundLineModel) -> bool:
    raw = line.inventory_id
    if raw is None:
        return False
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return False
    return n > 0


@router.patch("/outbound-lines/{line_id}/bind-inventory")
def bind_outbound_line_inventory(line_id: int, data: OutboundLineBindInventoryBody):
    """未识别到库存 ID 的明细行，手动指定 inventory_id；已有关联时拒绝。"""
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")
    if _outbound_line_has_inventory_id(line):
        raise HTTPException(status_code=400, detail="该明细已关联库存，无法修改")
    if int(line.is_stocked_out or 0) == 1:
        raise HTTPException(status_code=400, detail="该明细已出库，无法修改绑定")
    inv_id = int(data.inventory_id)
    if inv_id <= 0:
        raise HTTPException(status_code=400, detail="inventory_id 无效")
    inv_rows = db.execute_query("SELECT [id] FROM [inventory] WHERE [id] = ? LIMIT 1", (inv_id,))
    if not inv_rows:
        raise HTTPException(status_code=404, detail="库存商品不存在")
    line.inventory_id = inv_id
    if data.quantity is not None:
        line.quantity = max(1, int(data.quantity))
    if not line.save():
        raise HTTPException(status_code=500, detail="保存失败")
    refresh_inventory_pending_outbound_qty([inv_id])
    return {"success": True, "line_id": int(line.id), "inventory_id": inv_id}


@router.post("/outbound-lines/{line_id}/stock-out")
def stock_out_order_outbound_line(line_id: int, data: OutboundStockOutBody):
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")
    if int(line.is_stocked_out or 0) == 1:
        raise HTTPException(status_code=400, detail="该明细已出库，不能重复出库")
    if line.inventory_id is None:
        raise HTTPException(status_code=400, detail="该明细未匹配库存，无法出库")
    inv_id = int(line.inventory_id)
    qty = max(1, int(line.quantity or 1))

    inv_rows = db.execute_query(
        "SELECT [quantity], [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
        (inv_id,),
    )
    if not inv_rows:
        raise HTTPException(status_code=404, detail="库存商品不存在")
    current_qty = int(inv_rows[0][0] or 0)
    warehouse_id = inv_rows[0][1]
    if int(line.stock_deducted or 0) == 0:
        if current_qty < qty:
            raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
        updated = db.execute_update(
            """
            UPDATE [inventory]
            SET [quantity] = COALESCE([quantity], 0) - ?,
                [pending_outbound_qty] = CASE
                    WHEN COALESCE([pending_outbound_qty], 0) >= ? THEN COALESCE([pending_outbound_qty], 0) - ?
                    ELSE 0
                END
            WHERE [id] = ?
            """,
            (qty, qty, qty, inv_id),
        )
        if updated <= 0:
            raise HTTPException(status_code=500, detail="库存更新失败")
        if warehouse_id is not None:
            db.execute_insert(
                """
                INSERT INTO [transactions] (
                    type, inventory_id, warehouse_id, quantity, remark, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "out",
                    inv_id,
                    warehouse_id,
                    qty,
                    (data.remark or "").strip() or f"订单手动出库 {line.order_no} / line#{line.id}",
                    int(time.time()),
                ),
            )

    line.is_stocked_out = 1
    line.stocked_out_at = int(time.time())
    if not line.save():
        raise HTTPException(status_code=500, detail="写入出库状态失败")
    refresh_inventory_pending_outbound_qty([inv_id])

    new_qty_rows = db.execute_query("SELECT [quantity] FROM [inventory] WHERE [id] = ? LIMIT 1", (inv_id,))
    new_qty = int(new_qty_rows[0][0] or 0) if new_qty_rows else 0
    return {
        "success": True,
        "line_id": int(line.id),
        "order_no": str(line.order_no or ""),
        "inventory_id": inv_id,
        "stocked_out_quantity": qty,
        "new_inventory_quantity": new_qty,
    }


@router.post("/outbound-lines/manual")
def create_manual_outbound_line(data: ManualOutboundLineCreateBody):
    batch = ManualOutboundLinesBatchCreateBody(
        order_no=data.order_no,
        lines=[
            ManualOutboundLineItem(
                inventory_id=data.inventory_id,
                quantity=data.quantity,
                management_id=data.management_id,
            )
        ],
        remark=data.remark,
    )
    return create_manual_outbound_lines(batch)


@router.post("/outbound-lines/manual/batch")
def create_manual_outbound_lines(data: ManualOutboundLinesBatchCreateBody):
    ono = (data.order_no or "").strip()
    if not ono:
        raise HTTPException(status_code=400, detail="order_no 不能为空")
    rows = OrderModel.find_all(where="[order_no] = ?", params=(ono,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="订单不存在")
    lines = data.lines or []
    if not lines:
        raise HTTPException(status_code=400, detail="lines 不能为空")

    seen = set()
    normalized = []
    for it in lines:
        inv_id = int(it.inventory_id or 0)
        qty = int(it.quantity or 0)
        if inv_id <= 0:
            raise HTTPException(status_code=400, detail="存在无效 inventory_id")
        if qty <= 0:
            raise HTTPException(status_code=400, detail="数量必须大于0")
        if inv_id in seen:
            raise HTTPException(status_code=400, detail="同一库存商品请勿重复选择")
        seen.add(inv_id)
        normalized.append((inv_id, qty, (it.management_id or "").strip()))

    max_sort_rows = db.execute_query(
        "SELECT COALESCE(MAX([sort_index]), -1) FROM [order_outbound_lines] WHERE [order_no] = ?",
        (ono,),
    )
    next_sort = int(max_sort_rows[0][0] or -1) + 1

    created_ids: List[int] = []
    touched_inv_ids: List[int] = []
    created_items = []
    try:
        for idx, (inv_id, qty, mgmt) in enumerate(normalized):
            inv_rows = db.execute_query(
                "SELECT [quantity], [warehouse_id], [name] FROM [inventory] WHERE [id] = ? LIMIT 1",
                (inv_id,),
            )
            if not inv_rows:
                raise HTTPException(status_code=404, detail=f"库存商品不存在: {inv_id}")
            current_qty = int(inv_rows[0][0] or 0)
            warehouse_id = inv_rows[0][1]
            inv_name = str(inv_rows[0][2] or "").strip() or f"库存#{inv_id}"
            if current_qty < qty:
                raise HTTPException(status_code=400, detail=f"库存不足（inventory_id={inv_id}），当前库存：{current_qty}")

            token = mgmt or f"手动出库:{inv_name}"
            line = OrderOutboundLineModel(
                order_no=ono,
                inventory_id=inv_id,
                management_id=token,
                line_kind="manual",
                quantity=qty,
                sort_index=next_sort + idx,
                is_stocked_out=0,
                stocked_out_at=None,
                stock_deducted=1,
            )
            if not line.save():
                raise HTTPException(status_code=500, detail="保存手动出库明细失败")

            updated = db.execute_update(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? WHERE [id] = ?",
                (qty, inv_id),
            )
            if updated <= 0:
                raise HTTPException(status_code=500, detail=f"库存更新失败（inventory_id={inv_id}）")

            if warehouse_id is not None:
                db.execute_insert(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        inv_id,
                        warehouse_id,
                        qty,
                        (data.remark or "").strip() or f"订单待出库预扣减 {ono} / line#{line.id}",
                        int(time.time()),
                    ),
                )
            created_ids.append(int(line.id))
            touched_inv_ids.append(inv_id)
            created_items.append({"line_id": int(line.id), "inventory_id": inv_id, "quantity": qty})
    except Exception:
        for lid in created_ids:
            try:
                obj = OrderOutboundLineModel.find_by_id(id=lid)
                if obj:
                    obj.delete()
            except Exception:
                pass
        raise

    refresh_inventory_pending_outbound_qty(touched_inv_ids)
    return {"success": True, "order_no": ono, "items": created_items}


@router.get("")
def list_orders(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
):
    _validate_status_query(status)
    return OrderModel.find_detail_list(
        keyword=keyword,
        status=status,
        start_ts=start_ts,
        end_ts=end_ts,
        owner_user_id=owner_user_id,
        page=page,
        page_size=page_size,
    )


@router.post("/packaging-waive")
def waive_order_packaging(data: OrderPackagingWaiveBody):
    """待评价/已完成：确认本单不使用包材后不再标红。"""
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="订单不存在")
    item = rows[0]
    item.packaging_waived = 1
    if not item.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return item.to_dict()


@router.post("/refresh-info")
async def refresh_order_info(data: RefreshOrderInfoBody):
    """WebDriver 打开 jp.mercari.com/transaction/m{订单号}，MITM 截获 transaction_evidences/get 后更新状态、金额等字段。"""
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    du = (data.data_user or "").strip()
    if not du:
        raise HTTPException(status_code=400, detail="卖家ID（data_user）不能为空")

    aid = resolve_account_id_by_seller_id(du)
    if aid is None:
        raise HTTPException(
            status_code=400,
            detail="未找到与该卖家ID绑定的 active 煤炉账号，请在账号管理中配置 seller_id",
        )

    async def _do_refresh() -> dict:
        err = await apply_item_info_to_order(order_no, account_id=aid, expected_seller_id=du)
        if err == "order_not_found":
            raise HTTPException(status_code=404, detail="本地不存在该订单号")
        if err == "seller_mismatch":
            raise HTTPException(
                status_code=400,
                detail="接口返回的商品不属于该卖家，请检查订单号与卖家ID是否匹配",
            )
        if err and err.startswith("api:"):
            raise HTTPException(status_code=502, detail=err[4:])
        if err and err.startswith("request:"):
            raise HTTPException(status_code=502, detail=err[8:])
        if err == "save_failed":
            raise HTTPException(status_code=500, detail="写入数据库失败")
        if err:
            raise HTTPException(status_code=400, detail=err)

        rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not rows:
            raise HTTPException(status_code=404, detail="订单不存在")
        return rows[0].to_dict()

    try:
        return await run_meilu_serial_async(queue_key_for_meilu_account(int(aid)), _do_refresh)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@router.post("")
def create_order(data: OrderCreate):
    order_no = _normalize_order_no(data.order_no)
    _validate_order_status(data.status)
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于0")
    ou = data.order_updated_at
    pt = data.purchase_time
    item = OrderModel(
        order_no=order_no,
        order_date=int(data.order_date),
        order_updated_at=None if ou is None else int(ou),
        purchase_time=None if pt is None else int(pt),
        customer_name=(data.customer_name or "").strip() or None,
        data_user=(data.data_user or "").strip() or None,
        status=data.status,
        amount=int(data.amount),
        service_fee=data.service_fee,
        net_income=data.net_income,
        carrier_display_name=(data.carrier_display_name or "").strip() or None,
        request_class_display_name=(data.request_class_display_name or "").strip() or None,
        shipping_fee=data.shipping_fee,
        tracking_no=(data.tracking_no or "").strip() or None,
        transaction_evidence_id=data.transaction_evidence_id,
        remark=data.remark,
        description=data.description,
        thumbnails=_encode_thumbnails(data.thumbnails),
    )
    if not item.save():
        raise HTTPException(status_code=400, detail="保存失败，订单号可能重复")
    sync_outbound_lines_for_order(order_no, item.description)
    return item.to_dict()


@router.put("/{oid}")
def update_order(oid: int, data: OrderUpdate):
    item = OrderModel.find_by_id(id=oid)
    if not item:
        raise HTTPException(status_code=404, detail="订单不存在")

    old_status = str(item.status or "").strip()
    if data.order_no is not None:
        item.order_no = _normalize_order_no(data.order_no)
    if data.order_date is not None:
        item.order_date = int(data.order_date)
    if "order_updated_at" in data.model_fields_set:
        v = data.order_updated_at
        item.order_updated_at = None if v is None else int(v)
    if "purchase_time" in data.model_fields_set:
        v = data.purchase_time
        item.purchase_time = None if v is None else int(v)
    if data.customer_name is not None:
        item.customer_name = data.customer_name.strip() or None
    if "data_user" in data.model_fields_set:
        item.data_user = (data.data_user or "").strip() or None
    if data.status is not None:
        _validate_order_status(data.status)
        item.status = data.status
    if data.amount is not None:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="金额必须大于0")
        item.amount = int(data.amount)
    if "service_fee" in data.model_fields_set:
        item.service_fee = data.service_fee
    if "net_income" in data.model_fields_set:
        item.net_income = data.net_income
    if "carrier_display_name" in data.model_fields_set:
        item.carrier_display_name = (data.carrier_display_name or "").strip() or None
    if "request_class_display_name" in data.model_fields_set:
        item.request_class_display_name = (data.request_class_display_name or "").strip() or None
    if "shipping_fee" in data.model_fields_set:
        item.shipping_fee = data.shipping_fee
    if "tracking_no" in data.model_fields_set:
        item.tracking_no = (data.tracking_no or "").strip() or None
    if "transaction_evidence_id" in data.model_fields_set:
        item.transaction_evidence_id = data.transaction_evidence_id
    if "remark" in data.model_fields_set:
        item.remark = (data.remark or "").strip() or None
    if "description" in data.model_fields_set:
        item.description = (data.description or "").strip() or None
    if "thumbnails" in data.model_fields_set:
        item.thumbnails = _encode_thumbnails(data.thumbnails)

    if not item.save():
        raise HTTPException(status_code=400, detail="更新失败，订单号可能重复")
    sync_outbound_lines_for_order(item.order_no, item.description)
    if old_status != str(item.status or "").strip():
        refresh_inventory_pending_outbound_qty(_inventory_ids_for_order(item.order_no))
    return item.to_dict()


@router.delete("/{oid}")
def delete_order(oid: int):
    item = OrderModel.find_by_id(id=oid)
    if not item:
        raise HTTPException(status_code=404, detail="订单不存在")
    ono = (item.order_no or "").strip()
    if ono:
        touched_ids = _inventory_ids_for_order(ono)
        OrderOutboundLineModel.delete_all("[order_no] = ?", (ono,))
        refresh_inventory_pending_outbound_qty(touched_ids)
    if not item.delete():
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": "删除成功"}
