# -*- coding: utf-8 -*-
"""库存计数器：在售(on_sale_quantity) 的事件驱动维护，以及可上架(listable_quantity) 的派生重算。

数量模型（出品 1 件 = 1）：
  · 库存 quantity   = 物理总持有数，仅由入库/出库（扫码、组合）变动；上架/下架/售出都不改它。
  · 在售 on_sale_quantity = 当前已挂在售（含暂停 stop）的件数，事件驱动维护：
        - 上架成功 / 详情绑定后仍在售：在售 +1
        - 暂停出售(on_sale→stop) / 恢复出售(stop→on_sale)：不变
        - 下架/删除 或 售出（从在售消失）：在售 -1
  · 待出 pending_outbound_qty = 非终态订单且未出库的明细合计，由订单管线派生维护
        （见 description_mgmt_ids.refresh_inventory_pending_outbound_qty）。
  · 可上架 listable_quantity = max(0, 库存 - 在售 - 待出)，落库的派生值，出品可否以此判断。

「在售」的增减统一由本模块在「在售列表同步」(sync.apply_on_sale_list_sync) 与「详情绑定」
(detail_sync) 两处通过 ``reconcile_listing_counts`` 应用，并以 ``on_sale_items.counted_on_sale``
标记保证幂等（同步重复运行不会重复增减）。下架与售出都只是「从在售消失」→ 在售 -1，库存不变，
因此无需区分二者（待出由订单派生）。

``listable_quantity`` 在「在售/待出」变动处即时重算；库存列表读取时也会自愈
（见 inventory_helpers._query_inventory_with_joins）。
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..db_manage.database import DatabaseManager
from .on_sale.on_sale_items_sync.inventory_qty import (
    _mercari_id_lookup_keys,
    _split_mercari_item_ids,
)

log = logging.getLogger(__name__)

# 视为「仍挂在售（占用在售名额）」的煤炉状态：含暂停 stop（暂停不释放在售名额）
LISTED_STATUSES: Tuple[str, ...] = ("on_sale", "stop")


def _norm_keys(item_id: str) -> List[str]:
    """item_id 的查询键（兼容 m 前缀与纯数字）。"""
    return _mercari_id_lookup_keys(item_id)


def _listable_sql_expr() -> str:
    """可上架 = max(0, 库存 - 在售 - 待出) 的 SQL 表达式（基于同表列）。"""
    return (
        "MAX(0, COALESCE([quantity], 0) "
        "- COALESCE([on_sale_quantity], 0) "
        "- COALESCE([pending_outbound_qty], 0))"
    )


def recompute_listable_quantity(inv_ids: Optional[Iterable[int]] = None) -> int:
    """重算并落库 inventory.listable_quantity = max(0, 库存 - 在售 - 待出)。

    inv_ids 为空时重算全表；返回受影响行数。
    """
    db = DatabaseManager()
    expr = _listable_sql_expr()
    if inv_ids is None:
        return int(db.execute_update(
            f"UPDATE [inventory] SET [listable_quantity] = {expr}"
        ) or 0)
    ids = sorted({int(i) for i in inv_ids if i is not None})
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    return int(db.execute_update(
        f"UPDATE [inventory] SET [listable_quantity] = {expr} WHERE [id] IN ({ph})",
        tuple(ids),
    ) or 0)


def _adjust_on_sale(db: DatabaseManager, inv_id: int, on_sale_delta: int) -> bool:
    """对单个库存行的在售数量应用增量（clamp >= 0），并同步重算可上架。返回是否实际更新。"""
    if on_sale_delta == 0:
        return False
    changed = db.execute_update(
        """
        UPDATE [inventory]
        SET [on_sale_quantity] = MAX(0, COALESCE([on_sale_quantity], 0) + ?)
        WHERE [id] = ?
        """,
        (int(on_sale_delta), int(inv_id)),
    )
    recompute_listable_quantity([int(inv_id)])
    return bool(changed)


def _set_counted_flag(db: DatabaseManager, item_id: str, flag: int) -> None:
    """按 on_sale_items.item_id 设置 counted_on_sale 标记。"""
    iid = str(item_id or "").strip()
    if not iid:
        return
    db.execute_update(
        "UPDATE [on_sale_items] SET [counted_on_sale] = ? WHERE TRIM([item_id]) = TRIM(?)",
        (int(flag), iid),
    )


def _bound_inventory_map(db: DatabaseManager) -> Dict[str, Set[int]]:
    """构建「煤炉商品 ID（含规范化键）→ 绑定的库存 id 集合」。

    inventory.mercari_item_id 可能一行多 ID（、分隔），逐个拆分匹配。
    """
    rows = db.execute_query(
        """
        SELECT [id], [mercari_item_id]
        FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0
          AND TRIM(IFNULL([mercari_item_id], '')) != ''
        """
    )
    out: Dict[str, Set[int]] = {}
    for inv_id_raw, mids_raw in rows or []:
        try:
            inv_id = int(inv_id_raw)
        except (TypeError, ValueError):
            continue
        for mid in _split_mercari_item_ids(mids_raw):
            for key in _norm_keys(mid):
                out.setdefault(key, set()).add(inv_id)
    return out


def _load_listing_states(
    db: DatabaseManager, item_ids: Iterable[str]
) -> Dict[str, Dict[str, object]]:
    """按 item_id 读取 on_sale_items 的 status / is_delete / counted_on_sale（未软删的最新一条）。

    返回 {规范化键: {item_id, status, is_delete, counted}}。同一商品多键都会指向同一状态。
    """
    cleaned: List[str] = []
    seen: Set[str] = set()
    for raw in item_ids:
        for key in _norm_keys(raw):
            if key not in seen:
                seen.add(key)
                cleaned.append(key)
    if not cleaned:
        return {}
    ph = ",".join("?" * len(cleaned))
    rows = db.execute_query(
        f"""
        SELECT [item_id], [status], COALESCE([is_delete], 0), COALESCE([counted_on_sale], 0)
        FROM [on_sale_items]
        WHERE TRIM([item_id]) IN ({ph})
        ORDER BY [id] DESC
        """,
        tuple(cleaned),
    )
    out: Dict[str, Dict[str, object]] = {}
    for item_id, status, is_delete, counted in rows or []:
        state = {
            "item_id": str(item_id or "").strip(),
            "status": (str(status or "").strip() or None),
            "is_delete": int(is_delete or 0),
            "counted": int(counted or 0),
        }
        for key in _norm_keys(str(item_id or "")):
            out.setdefault(key, state)
    return out


def reconcile_listing_counts(item_ids: Iterable[str]) -> Dict[str, int]:
    """对给定煤炉商品 ID 集合，依据 on_sale_items 当前状态与绑定库存，对齐「在售」计数（库存不变）。

    幂等：凭 on_sale_items.counted_on_sale 标记，仅在「应计入」状态翻转时增减在售。
      · counted 0 → 应计入(未软删 + status∈on_sale/stop + 已绑定存在库存)：上架 → 在售 +1，标记=1
      · counted 1 → 不应计入(软删/下架/售出从在售消失，或解绑)：在售 -1，标记=0
      · 其余（暂停/恢复、未绑定、状态不变）：不动

    库存 quantity 不在此变动（仅入库/出库改变）；可上架由 _adjust_on_sale 同步重算。
    返回统计 {listed_inc, listed_dec}。
    """
    db = DatabaseManager()
    states = _load_listing_states(db, item_ids)
    if not states:
        return {"listed_inc": 0, "listed_dec": 0}

    bound_map = _bound_inventory_map(db)

    # 去重：按 item_id 唯一处理（多键指向同一 state）
    unique_states: Dict[str, Dict[str, object]] = {}
    for state in states.values():
        iid = str(state.get("item_id") or "").strip()
        if iid:
            unique_states[iid] = state

    stats = {"listed_inc": 0, "listed_dec": 0}

    for iid, state in unique_states.items():
        status = state.get("status")
        is_delete = int(state.get("is_delete") or 0)
        counted = int(state.get("counted") or 0)

        bound: Set[int] = set()
        for key in _norm_keys(iid):
            bound |= bound_map.get(key, set())

        should_count = (
            is_delete == 0
            and (status in LISTED_STATUSES)
            and bool(bound)
        )

        if should_count and counted == 0:
            # 上架：每个绑定库存 在售 +1（库存不变）
            for inv_id in bound:
                _adjust_on_sale(db, inv_id, +1)
            _set_counted_flag(db, iid, 1)
            stats["listed_inc"] += len(bound)
        elif not should_count and counted == 1:
            # 退出在售（下架/售出/解绑）：每个绑定库存 在售 -1（库存不变；待出由订单派生）
            for inv_id in bound:
                _adjust_on_sale(db, inv_id, -1)
                stats["listed_dec"] += 1
            _set_counted_flag(db, iid, 0)
        # 其余情形：暂停/恢复（counted 保持 1）、未绑定（counted 保持 0）等，不动

    if stats["listed_inc"] or stats["listed_dec"]:
        log.info("[inventory_counters] reconcile %s -> %s", list(unique_states.keys()), stats)
    return stats
