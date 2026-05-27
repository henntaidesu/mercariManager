# -*- coding: utf-8 -*-
"""出库明细相关端点与订单刷新/包装免列入端点。"""
import re
import time
from typing import List

from fastapi import Depends, HTTPException

from ....auth import require_auth
from ....db_manage.models.order import OrderModel
from ....db_manage.models.order_outbound_line import OrderOutboundLineModel
from ....use_mercari.get_order.description_mgmt_ids import (
    refresh_inventory_pending_outbound_qty,
)
from ....use_mercari.get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ....use_mercari.sync_data import resolve_account_id_by_seller_id
from ....use_mercari.sync_progress import (
    clear_sync_progress,
    get_sync_progress,
)
from ....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from .orders_helpers import _outbound_line_has_inventory_id, db
from .orders_models import (
    ManualOutboundLineCreateBody,
    ManualOutboundLineItem,
    ManualOutboundLinesBatchCreateBody,
    OrderPackagingWaiveBody,
    OutboundLineBindInventoryBody,
    OutboundLineConvertOwnerBody,
    OutboundStockOutBody,
    RefreshOrderInfoBody,
)


def _is_stock_holding_line(line: OrderOutboundLineModel) -> bool:
    """该明细对绑定库存仍有「占用」需要回吐：已出库或已预扣的均算占用。"""
    if int(line.is_stocked_out or 0) == 1:
        return True
    return int(line.stock_deducted or 0) == 1


def bind_outbound_line_inventory(line_id: int, data: OutboundLineBindInventoryBody):
    """未匹配/已匹配的明细行手动指定或重新绑定 inventory_id；已出库或已预扣的会回退旧库存并扣减新库存。"""
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")

    inv_id = int(data.inventory_id)
    if inv_id <= 0:
        raise HTTPException(status_code=400, detail="inventory_id 无效")
    inv_rows = db.execute_query(
        "SELECT [id], [quantity], [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
        (inv_id,),
    )
    if not inv_rows:
        raise HTTPException(status_code=404, detail="库存商品不存在")

    old_inv_id = int(line.inventory_id) if _outbound_line_has_inventory_id(line) else None
    old_qty = max(1, int(line.quantity or 1))
    new_qty = max(1, int(data.quantity if data.quantity is not None else old_qty))
    holds_stock = _is_stock_holding_line(line)
    no_op = old_inv_id == inv_id and new_qty == old_qty
    touched_inv_ids: List[int] = [inv_id]

    if no_op:
        return {"success": True, "line_id": int(line.id), "inventory_id": inv_id}

    if holds_stock:
        new_inv_qty = int(inv_rows[0][1] or 0)
        new_inv_warehouse_id = inv_rows[0][2]
        if new_inv_qty < new_qty:
            raise HTTPException(status_code=400, detail=f"目标库存不足，当前库存：{new_inv_qty}")

        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            if old_inv_id is not None and old_inv_id != inv_id:
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
                    (old_qty, old_inv_id),
                )
                touched_inv_ids.append(old_inv_id)
            elif old_inv_id == inv_id and new_qty != old_qty:
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
                    (old_qty, inv_id),
                )

            cur.execute(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? WHERE [id] = ?",
                (new_qty, inv_id),
            )

            if int(line.is_stocked_out or 0) == 1 and new_inv_warehouse_id is not None:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        inv_id,
                        new_inv_warehouse_id,
                        new_qty,
                        f"订单出库改绑 {line.order_no} / line#{line.id}",
                        int(time.time()),
                    ),
                )

            cur.execute(
                "UPDATE [order_outbound_lines] SET [inventory_id] = ?, [quantity] = ? WHERE [id] = ?",
                (inv_id, new_qty, int(line.id)),
            )
            conn.commit()
    else:
        line.inventory_id = inv_id
        line.quantity = new_qty
        if not line.save():
            raise HTTPException(status_code=500, detail="保存失败")
        if old_inv_id is not None and old_inv_id != inv_id:
            touched_inv_ids.append(old_inv_id)

    refresh_inventory_pending_outbound_qty(list(set(touched_inv_ids)))
    return {"success": True, "line_id": int(line.id), "inventory_id": inv_id, "quantity": new_qty}


def convert_outbound_line_owner(
    line_id: int,
    data: OutboundLineConvertOwnerBody,
    claims: dict = Depends(require_auth),
):
    """商品归属转化：把当前明细绑定的库存按行数量拆分到一条新管理番号下并改写归属，再把明细重绑到该新库存。

    仅允许 admin 账号调用（前端按钮也仅 admin 可见）。

    - 校验目标用户存在且不同于当前归属。
    - 未出库（未预扣）：从原库存扣减 line.quantity 给新库存（持有库存）。
    - 已出库或已预扣：从原库存回吐 line.quantity，再从新库存扣减同数量（保证账面占用转到新归属）。
    - 重绑后刷新两条库存的待出库汇总。
    """
    if str((claims or {}).get("username") or "").strip() != "admin":
        raise HTTPException(status_code=403, detail="仅 admin 账号可执行商品归属转化")
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")
    if not _outbound_line_has_inventory_id(line):
        raise HTTPException(status_code=400, detail="该明细尚未关联库存，请先编辑绑定库存")

    target_owner = int(data.owner_user_id or 0)
    if target_owner <= 0:
        raise HTTPException(status_code=400, detail="目标商品归属无效")
    owner_rows = db.execute_query("SELECT [id] FROM [users] WHERE [id] = ? LIMIT 1", (target_owner,))
    if not owner_rows:
        raise HTTPException(status_code=400, detail="目标商品归属用户不存在")

    src_id = int(line.inventory_id)
    src_rows = db.execute_query(
        """
        SELECT [name], [barcode], [category_id], [product_type_id], [owner_user_id], [warehouse_id],
               [price], [quantity], [description], [listing_title], [listing_body],
               [image], [image_front], [image_back], [images_json], [is_combined]
        FROM [inventory] WHERE [id] = ? LIMIT 1
        """,
        (src_id,),
    )
    if not src_rows:
        raise HTTPException(status_code=404, detail="原库存不存在")
    src = src_rows[0]
    if int(src[15] or 0) == 1:
        raise HTTPException(status_code=400, detail="组合商品不能进行归属转化")
    if int(src[4] or 0) == target_owner:
        raise HTTPException(status_code=400, detail="目标归属与当前归属一致")

    src_quantity = int(src[7] or 0)
    qty = max(1, int(line.quantity or 1))
    holds_stock = _is_stock_holding_line(line)
    # 未出库（未预扣）：需从原库存实际拨出 qty 给新库存；原库存须够
    if not holds_stock and src_quantity < qty:
        raise HTTPException(status_code=400, detail=f"原库存不足以转化，当前库存：{src_quantity}")

    import uuid as _uuid
    from ...image_storage import get_image_root
    import os as _os
    import shutil as _shutil

    def _dup(path):
        if not path or not isinstance(path, str) or not path.startswith("/imges/"):
            return path
        fn = path.split("/imges/", 1)[1].strip("/")
        if not fn:
            return path
        s = _os.path.join(get_image_root(), fn)
        if not _os.path.exists(s):
            return path
        ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "jpg"
        new_name = f"inv_split_{_uuid.uuid4().hex}.{ext}"
        d = _os.path.join(get_image_root(), new_name)
        try:
            _shutil.copyfile(s, d)
        except Exception:
            return path
        return f"/imges/{new_name}"

    import json as _json
    src_images_json = src[14]
    src_paths: List[str] = []
    try:
        if src_images_json:
            parsed = _json.loads(src_images_json)
            if isinstance(parsed, list):
                for p in parsed:
                    if p and str(p).strip():
                        src_paths.append(str(p).strip())
    except Exception:
        src_paths = []
    if not src_paths:
        for p in [src[12], src[11], src[13]]:
            if p and str(p).strip():
                src_paths.append(str(p).strip())

    new_paths = [_dup(p) for p in src_paths]
    new_image = new_paths[0] if new_paths else None
    new_image_front = new_image
    new_image_back = new_paths[1] if len(new_paths) > 1 else None
    new_images_json = (
        _json.dumps(new_paths, ensure_ascii=False, separators=(",", ":")) if new_paths else None
    )

    new_barcode = f"SPLIT-{int(time.time() * 1000)}-{_uuid.uuid4().hex[:6]}"

    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            if not holds_stock:
                # 未出库：把 qty 从原库存搬到新库存，新库存 quantity = qty
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? WHERE [id] = ?",
                    (qty, src_id),
                )
                new_qty_value = qty
            else:
                # 已出库或已预扣：账面上这 qty 已被占用，原库存先回吐再用新库存扣减
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
                    (qty, src_id),
                )
                # 新库存先以 qty 起始（克隆），再立刻扣减 qty 占用，结果为 0
                new_qty_value = 0

            cur.execute(
                """
                INSERT INTO [inventory] (
                    name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                    mercari_item_id, on_sale_quantity, pending_outbound_qty,
                    description, listing_title, listing_body, image, image_front, image_back, images_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src[0], new_barcode, src[2], src[3], target_owner, src[5], src[6], new_qty_value,
                    None, 0, 0,
                    src[8], src[9], src[10],
                    new_image, new_image_front, new_image_back, new_images_json,
                ),
            )
            new_inv_id = cur.lastrowid

            if int(line.is_stocked_out or 0) == 1:
                # 已出库：在新库存上补一笔出库 transactions（仓库取新库存继承的 warehouse_id）
                if src[5] is not None:
                    cur.execute(
                        """
                        INSERT INTO [transactions] (
                            type, inventory_id, warehouse_id, quantity, remark, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "out",
                            new_inv_id,
                            src[5],
                            qty,
                            f"订单归属转化（已出库） {line.order_no} / line#{line.id}",
                            int(time.time()),
                        ),
                    )

            cur.execute(
                "UPDATE [order_outbound_lines] SET [inventory_id] = ? WHERE [id] = ?",
                (new_inv_id, int(line.id)),
            )
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="商品归属转化失败，请稍后重试")

    refresh_inventory_pending_outbound_qty([src_id, int(new_inv_id)])
    return {
        "success": True,
        "line_id": int(line.id),
        "old_inventory_id": src_id,
        "new_inventory_id": int(new_inv_id),
        "owner_user_id": target_owner,
        "quantity": qty,
    }


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


_REFRESH_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


async def refresh_order_info(data: RefreshOrderInfoBody):
    """WebDriver 打开 jp.mercari.com/transaction/m{订单号}，MITM 截获 transaction_evidences/get 后更新状态、金额等字段。

    ``progress_job_id`` 配合 GET /use_web/orders/refresh-progress/{job_id} 让前端轮询展示步骤。
    """
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    du = (data.data_user or "").strip()
    if not du:
        raise HTTPException(status_code=400, detail="卖家ID（data_user）不能为空")

    jid = (data.progress_job_id or "").strip() or None
    if jid and not _REFRESH_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    aid = resolve_account_id_by_seller_id(du)
    if aid is None:
        raise HTTPException(
            status_code=400,
            detail="未找到与该卖家ID绑定的 active 煤炉账号，请在账号管理中配置 seller_id",
        )

    async def _do_refresh() -> dict:
        err = await apply_item_info_to_order(
            order_no,
            account_id=aid,
            expected_seller_id=du,
            progress_job_id=jid,
        )
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
        return await run_mercari_serial_async(queue_key_for_mercari_account(int(aid)), _do_refresh)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)


def refresh_order_progress(job_id: str):
    """订单单行刷新进度轮询（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _REFRESH_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}
