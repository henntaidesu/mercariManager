# -*- coding: utf-8 -*-
"""
订单「货物比例 / 比例价格」权重：与 routes.orders list_order_outbound_lines 一致
（bundle_title 在售匹配价；否则按库存价×件数含手动出库），供包材按归属拆分、订单金额按归属拆分等复用。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .db_manage.database import DatabaseManager
from .db_manage.models.order_outbound_line import OrderOutboundLineModel

_db = DatabaseManager()


def _apply_inventory_line_ratio_pricing(items: List[Dict[str, Any]], order_amount: int) -> bool:
    """
    对「已关联库存、且尚无 ratio_price」的出库行（manual / mgmt_id / barcode 等），
    按库存原价 × 件数（原价为 0 则退化为件数）将订单金额分摊到各行，写入 goods_ratio、ratio_price。
    """
    order_amount = int(order_amount or 0)
    if order_amount <= 0:
        return False

    weighted: List[Tuple[Dict[str, Any], int]] = []
    for it in items:
        if it.get("inventory_id") is None:
            continue
        if it.get("ratio_price") is not None:
            continue
        qty = max(1, int(it.get("quantity") or 1))
        pr = it.get("original_price")
        try:
            pi = max(0, int(pr) if pr is not None else 0)
        except (TypeError, ValueError):
            pi = 0
        w = int(pi) * int(qty)
        if w <= 0:
            w = int(qty)
        weighted.append((it, int(w)))

    if not weighted:
        return False

    weights = [w for _, w in weighted]
    sum_w = sum(weights)
    if sum_w <= 0:
        return False

    floors: List[int] = []
    fracs: List[float] = []
    for w in weights:
        raw_total = order_amount * (float(w) / float(sum_w))
        f = int(raw_total)
        floors.append(f)
        fracs.append(raw_total - f)

    remain = order_amount - sum(floors)
    alloc_totals = floors[:]
    if remain > 0:
        idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
        for i in idxs[:remain]:
            alloc_totals[i] += 1

    for i, (it, w) in enumerate(weighted):
        it["goods_ratio"] = float(w) / float(sum_w) if sum_w > 0 else None
        it["ratio_price"] = int(alloc_totals[i])
    return True


def apply_bundle_title_ratio_pricing(items: List[Dict[str, Any]], order_amount: int) -> bool:
    """
    优先为 bundle_title 行按在售「组合标题」匹配价写入 goods_ratio、ratio_price；
    若无法完成（无组合行、金额≤0、在售权重为 0 等），再对仍无 ratio_price 且已关联库存的行
    （含手动出库 manual、管理 ID、条码）按库存价×件数分摊。

    会先清空 items 中所有行的 goods_ratio / ratio_price。
    任一方式成功写入比例则返回 True。
    """
    for it in items:
        it["goods_ratio"] = None
        it["ratio_price"] = None

    order_amount = int(order_amount or 0)
    bundle_lines = [
        it for it in items if str(it.get("line_kind") or "").strip() == "bundle_title"
    ]
    bundle_ok = False
    if not bundle_lines or order_amount <= 0:
        return _apply_inventory_line_ratio_pricing(items, order_amount)

    def _normalize_match_text(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).casefold()

    titles: List[str] = [str(it.get("management_id") or "").strip() for it in bundle_lines]
    titles = [t for t in titles if t]
    title_set = list(dict.fromkeys(titles))

    on_sale_rows = _db.execute_query(
        """
        SELECT
            o.[item_id],
            TRIM(IFNULL(o.[name], '')) AS [name],
            COALESCE(o.[price], 0) AS [price],
            o.[updated],
            o.[created],
            o.[id]
        FROM [on_sale_items] o
        WHERE COALESCE(o.[is_delete], 0) = 0
          AND TRIM(IFNULL(o.[item_id], '')) != ''
          AND TRIM(IFNULL(o.[name], '')) != ''
        """
    )
    on_sale_records = []
    for item_id_raw, name_raw, price_raw, updated_raw, created_raw, oid_raw in on_sale_rows:
        name_str = str(name_raw or "").strip()
        item_id_str = str(item_id_raw or "").strip()
        if not name_str or not item_id_str:
            continue
        name_norm = _normalize_match_text(name_str)
        try:
            updated_i = int(updated_raw) if updated_raw is not None else 0
        except (TypeError, ValueError):
            updated_i = 0
        try:
            created_i = int(created_raw) if created_raw is not None else 0
        except (TypeError, ValueError):
            created_i = 0
        try:
            oid_i = int(oid_raw) if oid_raw is not None else 0
        except (TypeError, ValueError):
            oid_i = 0
        try:
            price_i = int(price_raw or 0)
        except (TypeError, ValueError):
            price_i = 0

        on_sale_records.append(
            {
                "item_id": item_id_str,
                "name_norm": name_norm,
                "price": price_i,
                "updated": updated_i,
                "created": created_i,
                "id": oid_i,
            }
        )

    latest_price_by_title: dict = {}
    for title in title_set:
        target_norm = _normalize_match_text(title)
        exact_candidates = []
        fuzzy_candidates = []
        for rec in on_sale_records:
            nn = rec.get("name_norm") or ""
            if not nn:
                continue
            if nn == target_norm:
                exact_candidates.append(rec)
            elif target_norm and (target_norm in nn or nn in target_norm):
                fuzzy_candidates.append(rec)
        candidates = exact_candidates if exact_candidates else fuzzy_candidates
        if not candidates:
            latest_price_by_title[title] = None
            continue
        best = max(
            candidates,
            key=lambda c: (int(c.get("updated") or 0), int(c.get("created") or 0), int(c.get("id") or 0)),
        )
        latest_price_by_title[title] = int(best.get("price") or 0)

    weights: List[int] = []
    for it in bundle_lines:
        qty = max(1, int(it.get("quantity") or 1))
        title = str(it.get("management_id") or "").strip()
        op = latest_price_by_title.get(title)
        it["original_price"] = op
        op_int = int(op) if op is not None else 0
        w = max(0, op_int) * qty
        weights.append(w)

    sum_w = sum(weights)
    if sum_w > 0:
        floors: List[int] = []
        fracs: List[float] = []
        for w in weights:
            raw_total = order_amount * (float(w) / float(sum_w))
            f = int(raw_total)
            floors.append(f)
            fracs.append(raw_total - f)

        remain = order_amount - sum(floors)
        alloc_totals = floors[:]
        if remain > 0:
            idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
            for i in idxs[:remain]:
                alloc_totals[i] += 1

        for i, it in enumerate(bundle_lines):
            it["goods_ratio"] = float(weights[i]) / float(sum_w) if sum_w > 0 else None
            it["ratio_price"] = int(alloc_totals[i])

        bundle_ok = True

    if bundle_ok:
        return True

    return _apply_inventory_line_ratio_pricing(items, order_amount)


def owner_weights_from_order_goods_ratio(order_no: str) -> List[Dict[str, Any]]:
    """
    若订单存在可计算的比例（组合标题在售价，或库存行价×件数；与订单二级表同源），
    返回 [{"owner": 展示名同商品归属, "weight": 整数权重}, ...]；
    weight 为该归属下各出库行的 ratio_price 之和（与订单金额分摊一致）。

    无法计算时返回 []，调用方应回退其它权重口径。
    """
    ono = (order_no or "").strip()
    if not ono:
        return []

    items = OrderOutboundLineModel.list_enriched_for_order(ono)
    order_rows = _db.execute_query(
        "SELECT COALESCE([amount], 0) FROM [orders] WHERE [order_no] = ? LIMIT 1",
        (ono,),
    )
    order_amount = int(order_rows[0][0] or 0) if order_rows else 0

    if not apply_bundle_title_ratio_pricing(items, order_amount):
        return []

    grouped: Dict[str, int] = {}
    for it in items:
        rp = it.get("ratio_price")
        if rp is None:
            continue
        owner = str(
            it.get("product_owner_name") or it.get("inventory_owner_name") or ""
        ).strip()
        if not owner:
            continue
        grouped[owner] = int(grouped.get(owner, 0)) + int(rp)

    return [
        {"owner": k, "weight": int(v)}
        for k, v in grouped.items()
        if int(v) > 0
    ]


def _allocate_int_by_weights(total: int, weights: Dict[int, int]) -> Dict[int, int]:
    """按正整数权重将 total 日元拆分给各 key，与 bundle 分摊相同的「先 floor 再按小数最大补 1」。"""
    total = int(total)
    if total <= 0 or not weights:
        return {}
    keys = [k for k, w in weights.items() if int(w) > 0]
    if not keys:
        return {}
    wvals = [int(weights[k]) for k in keys]
    sum_w = sum(wvals)
    if sum_w <= 0:
        return {}
    floors: List[int] = []
    fracs: List[float] = []
    for w in wvals:
        raw_total = total * (float(w) / float(sum_w))
        f = int(raw_total)
        floors.append(f)
        fracs.append(raw_total - f)
    remain = total - sum(floors)
    out = floors[:]
    if remain > 0:
        idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
        for i in idxs[:remain]:
            out[i] += 1
    return {keys[i]: int(out[i]) for i in range(len(keys))}


def _distinct_positive_owner_ids(items: List[Dict[str, Any]]) -> List[int]:
    out: List[int] = []
    seen = set()
    for it in items:
        raw = it.get("product_owner_user_id")
        if raw is None:
            raw = it.get("inventory_owner_user_id")
        if raw is None:
            continue
        try:
            oid = int(raw)
        except (TypeError, ValueError):
            continue
        if oid <= 0:
            continue
        if oid not in seen:
            seen.add(oid)
            out.append(oid)
    return out


def _fallback_owner_amount_and_basis(
    items: List[Dict[str, Any]], order_amount: int, owner_user_id: int
) -> Tuple[int, str]:
    """无可用 bundle 比例时：按库存原价×件数（原价为 0 则退化为件数）汇总到各归属，再拆分订单金额。"""
    oid = int(owner_user_id)
    order_amount = int(order_amount or 0)
    if order_amount <= 0:
        return 0, "none"

    weight_by_owner: Dict[int, int] = {}
    for it in items:
        if it.get("inventory_id") is None:
            continue
        ou = it.get("product_owner_user_id")
        if ou is None:
            ou = it.get("inventory_owner_user_id")
        if ou is None:
            continue
        try:
            oui = int(ou)
        except (TypeError, ValueError):
            continue
        if oui <= 0:
            continue
        qty = max(1, int(it.get("quantity") or 1))
        pr = it.get("original_price")
        try:
            pi = max(0, int(pr) if pr is not None else 0)
        except (TypeError, ValueError):
            pi = 0
        w = max(0, pi) * qty
        if w <= 0:
            w = qty
        weight_by_owner[oui] = int(weight_by_owner.get(oui, 0)) + int(w)

    tw = sum(weight_by_owner.values())
    if tw > 0:
        alloc = _allocate_int_by_weights(order_amount, weight_by_owner)
        return int(alloc.get(oid, 0)), "inventory_price"

    owners = _distinct_positive_owner_ids(items)
    if oid in owners and len(owners) > 0:
        alloc = _allocate_int_by_weights(order_amount, {o: 1 for o in owners})
        return int(alloc.get(oid, 0)), "equal_owners"

    return 0, "none"


def split_order_money_for_owner_user(
    order_no: str,
    owner_user_id: int,
    amount_raw: Any,
    service_fee_raw: Any,
    shipping_fee_raw: Any,
    net_income_raw: Any,
) -> Dict[str, Any]:
    """
    按商品归属拆分一单上的金额、手续费、快递费、净收益（与二级表 ratio_price 一致：bundle 或库存行分摊；否则按库存价×件数）。

    返回 amount / service_fee / shipping_fee / net_income（与库字段同名，值为拆分后整数日元；
    原字段为 null 的仍返回 null）。
    """
    ono = (order_no or "").strip()
    oid = int(owner_user_id)
    amount = int(amount_raw or 0) if amount_raw is not None else 0

    if not ono or oid <= 0:
        return {
            "amount": amount,
            "service_fee": int(service_fee_raw) if service_fee_raw is not None else None,
            "shipping_fee": int(shipping_fee_raw) if shipping_fee_raw is not None else None,
            "net_income": int(net_income_raw) if net_income_raw is not None else None,
            "split_basis": "none",
        }

    items = OrderOutboundLineModel.list_enriched_for_order(ono)
    apply_bundle_title_ratio_pricing(items, amount)

    owner_amt = 0
    basis = "bundle"
    if amount > 0:
        for it in items:
            rp = it.get("ratio_price")
            if rp is None:
                continue
            u = it.get("product_owner_user_id")
            if u is None:
                u = it.get("inventory_owner_user_id")
            if u is not None and int(u) == oid:
                owner_amt += int(rp)
        if owner_amt > 0:
            has_non_bundle_ratio = any(
                str(it.get("line_kind") or "").strip() != "bundle_title"
                for it in items
                if it.get("ratio_price") is not None
            )
            if has_non_bundle_ratio:
                basis = "inventory_line"

    if owner_amt <= 0 and amount > 0:
        owner_amt, basis = _fallback_owner_amount_and_basis(items, amount, oid)

    if owner_amt <= 0 and amount > 0:
        distinct = _distinct_positive_owner_ids(items)
        if len(distinct) == 1 and distinct[0] == oid:
            owner_amt = amount
            basis = "full"
        elif oid in distinct and len(distinct) > 0:
            alloc = _allocate_int_by_weights(amount, {o: 1 for o in distinct})
            owner_amt = int(alloc.get(oid, 0))
            basis = "equal_owners"

    ratio = (float(owner_amt) / float(amount)) if amount > 0 else 1.0

    def _scale(v: Any) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            vi = int(v)
        except (TypeError, ValueError):
            return None
        return int(round(float(vi) * ratio))

    return {
        "amount": int(owner_amt),
        "service_fee": _scale(service_fee_raw),
        "shipping_fee": _scale(shipping_fee_raw),
        "net_income": _scale(net_income_raw),
        "split_basis": basis,
    }
