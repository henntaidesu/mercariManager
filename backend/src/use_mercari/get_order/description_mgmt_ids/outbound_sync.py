# -*- coding: utf-8 -*-
"""出库明细同步与待出库数量刷新 + SQL 片段"""
from __future__ import annotations

from typing import List, Optional
from ....db_manage.database import DatabaseManager
from ....db_manage.models.order_outbound_line import TERMINAL_ORDER_STATUSES, OrderOutboundLineModel
from ._common import _normalize_int_id, _normalize_match_text
from .inventory_resolve import _extract_bundle_product_titles, _inventory_id_by_barcode, _inventory_id_exists, _is_bundle_order_description, _resolve_inventory_id_by_bundle_title
from .parsing import parse_order_description_outbound_tokens_with_quantity


def refresh_inventory_pending_outbound_qty(inventory_ids: Optional[List[int]] = None) -> None:
    """
    将订单待出库汇总回写到 inventory.pending_outbound_qty：
    - 仅统计非终态订单
    - 仅统计 is_stocked_out != 1 的明细
    """
    db = DatabaseManager()
    inv_ids: List[int] = []
    if inventory_ids:
        seen = set()
        for raw in inventory_ids:
            iid = _normalize_int_id(raw)
            if iid is None or iid in seen:
                continue
            seen.add(iid)
            inv_ids.append(iid)
    if inv_ids:
        ph = ",".join("?" * len(inv_ids))
        db.execute_update(
            f"UPDATE [inventory] SET [pending_outbound_qty] = 0 WHERE [id] IN ({ph})",
            tuple(inv_ids),
        )
        term_ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
        bind = tuple(TERMINAL_ORDER_STATUSES) + tuple(inv_ids)
        rows = db.execute_query(
            f"""
            SELECT l.[inventory_id], SUM(COALESCE(l.[quantity], 1)) AS q
            FROM [order_outbound_lines] l
            INNER JOIN [orders] o ON o.[order_no] = l.[order_no]
            WHERE l.[inventory_id] IS NOT NULL
              AND COALESCE(l.[is_stocked_out], 0) = 0
              AND o.[status] NOT IN ({term_ph})
              AND l.[inventory_id] IN ({ph})
            GROUP BY l.[inventory_id]
            """,
            bind,
        )
    else:
        db.execute_update("UPDATE [inventory] SET [pending_outbound_qty] = 0")
        term_ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
        rows = db.execute_query(
            f"""
            SELECT l.[inventory_id], SUM(COALESCE(l.[quantity], 1)) AS q
            FROM [order_outbound_lines] l
            INNER JOIN [orders] o ON o.[order_no] = l.[order_no]
            WHERE l.[inventory_id] IS NOT NULL
              AND COALESCE(l.[is_stocked_out], 0) = 0
              AND o.[status] NOT IN ({term_ph})
            GROUP BY l.[inventory_id]
            """,
            tuple(TERMINAL_ORDER_STATUSES),
        )
    for inv_id_raw, qty_raw in rows:
        inv_id = _normalize_int_id(inv_id_raw)
        if inv_id is None:
            continue
        qty = max(0, int(qty_raw or 0))
        db.execute_update(
            "UPDATE [inventory] SET [pending_outbound_qty] = ? WHERE [id] = ?",
            (qty, inv_id),
        )
    # 待出变动后同步重算「可上架」= 库存 - 在售 - 待出
    from ...inventory_counters import recompute_listable_quantity

    recompute_listable_quantity(inv_ids if inv_ids else None)

def sync_outbound_lines_for_order(
    order_no: str,
    description: Optional[str],
    *,
    skip_if_has_lines: bool = False,
) -> None:
    """重写出库行后，重算并持久化该订单各行的「货物比例」（goods_ratio / ratio_price / ratio_unit_price），
    供订单列表 / 二级明细 / 统计 / 包材拆分直接读库，不再每次请求实时计算。

    包一层在所有出库行变更（含 skip_if_has_lines 跳过重建、但订单金额可能已变化的刷新场景）后统一重算。
    """
    _sync_outbound_lines_for_order_impl(
        order_no, description, skip_if_has_lines=skip_if_has_lines
    )
    # 延迟导入避免 use_mercari -> use_web 潜在环引用
    from ....use_web.orders.units.order_goods_ratio import recompute_and_store_order_ratio

    recompute_and_store_order_ratio((order_no or "").strip())


def _sync_outbound_lines_for_order_impl(
    order_no: str,
    description: Optional[str],
    *,
    skip_if_has_lines: bool = False,
) -> None:
    """
    根据最新商品说明重写该订单的 order_outbound_lines。
    无「管理ID:」「管理番号:」「バーコード:」或解析结果为空时，仅删除该订单原有明细。

    skip_if_has_lines：为 True 且该订单已有任意出库明细时，不再增删商品行（用于煤炉刷新订单信息）。

    校验：若某库存 ID 已在该订单的「手动出库」明细（line_kind=manual）中出现，则不再从说明
    写入同库存的 bundle_title / mgmt_id / barcode 行，避免重复。组合标题之间同一 inventory_id 仅保留一行。
    """
    ono = (order_no or "").strip()
    if not ono:
        return

    old_rows = OrderOutboundLineModel.find_all(
        where="[order_no] = ?",
        params=(ono,),
        order_by="sort_index ASC, id ASC",
    )
    if skip_if_has_lines and old_rows:
        return
    old_inv_ids = {
        int(r.inventory_id)
        for r in old_rows
        if r.inventory_id is not None and str(r.inventory_id).strip() != ""
    }
    old_state = {}
    old_manual_rows = []
    for r in old_rows:
        key = (
            str(r.line_kind or "").strip(),
            str(r.management_id or "").strip(),
            max(1, int(r.quantity or 1)),
            int(r.sort_index or 0),
        )
        old_state[key] = (
            int(r.is_stocked_out or 0),
            int(r.stocked_out_at) if r.stocked_out_at is not None else None,
            int(r.stock_deducted or 0),
        )
        if str(r.line_kind or "").strip() == "manual":
            old_manual_rows.append(r)

    manual_inv_ids = {
        int(mr.inventory_id)
        for mr in old_manual_rows
        if mr.inventory_id is not None and str(mr.inventory_id).strip() != ""
    }
    old_token_state: dict = {}
    for r in old_rows:
        lk = str(r.line_kind or "").strip()
        if lk not in ("mgmt_id", "barcode"):
            continue
        mid = str(r.management_id or "").strip()
        q = max(1, int(r.quantity or 1))
        old_token_state[(lk, mid, q)] = (
            int(r.is_stocked_out or 0),
            int(r.stocked_out_at) if r.stocked_out_at is not None else None,
            int(r.stock_deducted or 0),
        )

    OrderOutboundLineModel.delete_all("[order_no] = ?", (ono,))
    tokens = parse_order_description_outbound_tokens_with_quantity(description)
    if not tokens:
        if not _is_bundle_order_description(description):
            touched_inv_ids = set(old_inv_ids)
            for idx, mr in enumerate(old_manual_rows):
                line = OrderOutboundLineModel(
                    order_no=ono,
                    inventory_id=mr.inventory_id,
                    management_id=str(mr.management_id or f"manual_{idx + 1}"),
                    line_kind="manual",
                    quantity=max(1, int(mr.quantity or 1)),
                    sort_index=idx,
                    is_stocked_out=int(mr.is_stocked_out or 0),
                    stocked_out_at=mr.stocked_out_at,
                    stock_deducted=int(mr.stock_deducted or 0),
                )
                line.save()
                if mr.inventory_id is not None:
                    touched_inv_ids.add(int(mr.inventory_id))
            refresh_inventory_pending_outbound_qty(list(touched_inv_ids))
            return
        titles = _extract_bundle_product_titles(description)
        if not titles:
            touched_inv_ids = set(old_inv_ids)
            for idx, mr in enumerate(old_manual_rows):
                line = OrderOutboundLineModel(
                    order_no=ono,
                    inventory_id=mr.inventory_id,
                    management_id=str(mr.management_id or f"manual_{idx + 1}"),
                    line_kind="manual",
                    quantity=max(1, int(mr.quantity or 1)),
                    sort_index=idx,
                    is_stocked_out=int(mr.is_stocked_out or 0),
                    stocked_out_at=mr.stocked_out_at,
                    stock_deducted=int(mr.stock_deducted or 0),
                )
                line.save()
                if mr.inventory_id is not None:
                    touched_inv_ids.add(int(mr.inventory_id))
            refresh_inventory_pending_outbound_qty(list(touched_inv_ids))
            return
        old_bundle_state_by_norm: dict = {}
        for r in old_rows:
            if str(r.line_kind or "").strip() != "bundle_title":
                continue
            nt = _normalize_match_text(str(r.management_id or ""))
            if not nt:
                continue
            old_bundle_state_by_norm[nt] = (
                int(r.is_stocked_out or 0),
                int(r.stocked_out_at) if r.stocked_out_at is not None else None,
                int(r.stock_deducted or 0),
            )
        touched_inv_ids = set(old_inv_ids)
        bundle_inv_written: set[int] = set()
        sort_idx = 0
        for title in titles:
            inv_id = _resolve_inventory_id_by_bundle_title(title)
            if inv_id is not None:
                if inv_id in manual_inv_ids:
                    continue
                if inv_id in bundle_inv_written:
                    continue
                bundle_inv_written.add(inv_id)
            tnorm = _normalize_match_text(title)
            stocked, stocked_at, deducted = old_bundle_state_by_norm.get(
                tnorm, (0, None, 0)
            )
            line = OrderOutboundLineModel(
                order_no=ono,
                inventory_id=inv_id,
                management_id=title,
                line_kind="bundle_title",
                quantity=1,
                sort_index=sort_idx,
                is_stocked_out=stocked,
                stocked_out_at=stocked_at,
                stock_deducted=deducted,
            )
            line.save()
            sort_idx += 1
            if inv_id is not None:
                touched_inv_ids.add(int(inv_id))
        base_idx = sort_idx
        for off, mr in enumerate(old_manual_rows):
            line = OrderOutboundLineModel(
                order_no=ono,
                inventory_id=mr.inventory_id,
                management_id=str(mr.management_id or f"manual_{off + 1}"),
                line_kind="manual",
                quantity=max(1, int(mr.quantity or 1)),
                sort_index=base_idx + off,
                is_stocked_out=int(mr.is_stocked_out or 0),
                stocked_out_at=mr.stocked_out_at,
                stock_deducted=int(mr.stock_deducted or 0),
            )
            line.save()
            if mr.inventory_id is not None:
                touched_inv_ids.add(int(mr.inventory_id))
        refresh_inventory_pending_outbound_qty(list(touched_inv_ids))
        return

    touched_inv_ids = set(old_inv_ids)
    token_inv_written: set[int] = set()
    sort_idx = 0
    for _idx, (kind, val, qty) in enumerate(tokens):
        qn = max(1, int(qty or 1))
        if kind == "mgmt_id":
            mid = int(val)
            exists = _inventory_id_exists(mid)
            inv_for_line = mid if exists else None
            if inv_for_line is not None and inv_for_line in manual_inv_ids:
                continue
            if inv_for_line is not None and inv_for_line in token_inv_written:
                continue
            lk = "mgmt_id"
            mid_s = str(mid)
            stocked, stocked_at, deducted = old_token_state.get(
                (lk, mid_s, qn), (0, None, 0)
            )
            line = OrderOutboundLineModel(
                order_no=ono,
                inventory_id=inv_for_line,
                management_id=mid_s,
                line_kind="mgmt_id",
                quantity=qn,
                sort_index=sort_idx,
                is_stocked_out=stocked,
                stocked_out_at=stocked_at,
                stock_deducted=deducted,
            )
        else:
            bc = str(val).strip()
            inv_id = _inventory_id_by_barcode(bc)
            if inv_id is not None and inv_id in manual_inv_ids:
                continue
            if inv_id is not None and inv_id in token_inv_written:
                continue
            lk = "barcode"
            stocked, stocked_at, deducted = old_token_state.get(
                (lk, bc, qn), (0, None, 0)
            )
            line = OrderOutboundLineModel(
                order_no=ono,
                inventory_id=inv_id,
                management_id=bc,
                line_kind="barcode",
                quantity=qn,
                sort_index=sort_idx,
                is_stocked_out=stocked,
                stocked_out_at=stocked_at,
                stock_deducted=deducted,
            )
        line.save()
        sort_idx += 1
        if line.inventory_id is not None:
            token_inv_written.add(int(line.inventory_id))
            touched_inv_ids.add(int(line.inventory_id))
    base_idx = sort_idx
    for off, mr in enumerate(old_manual_rows):
        line = OrderOutboundLineModel(
            order_no=ono,
            inventory_id=mr.inventory_id,
            management_id=str(mr.management_id or f"manual_{off + 1}"),
            line_kind="manual",
            quantity=max(1, int(mr.quantity or 1)),
            sort_index=base_idx + off,
            is_stocked_out=int(mr.is_stocked_out or 0),
            stocked_out_at=mr.stocked_out_at,
            stock_deducted=int(mr.stock_deducted or 0),
        )
        line.save()
        if mr.inventory_id is not None:
            touched_inv_ids.add(int(mr.inventory_id))
    refresh_inventory_pending_outbound_qty(list(touched_inv_ids))

def sql_pending_outbound_subquery(alias: str = "p") -> str:
    """
    用于 SELECT 中追加列：某库存行在非终态订单中的待出库件数合计。
    """
    ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
    return f"""
        COALESCE((
            SELECT SUM(l.quantity)
            FROM [order_outbound_lines] l
            INNER JOIN [orders] o ON o.order_no = l.order_no
            WHERE l.inventory_id = {alias}.[id]
              AND COALESCE(l.is_stocked_out, 0) = 0
              AND o.status NOT IN ({ph})
        ), 0)
    """

def sql_pending_outbound_params() -> tuple:
    return tuple(TERMINAL_ORDER_STATUSES)
