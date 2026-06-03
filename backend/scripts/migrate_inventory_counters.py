# -*- coding: utf-8 -*-
"""对账脚本：依据当前数据，重建「在售 / 待出 / 可上架」与 on_sale_items.counted_on_sale 标记。

数量模型（出品 1 件 = 1，详见 src/use_mercari/inventory_counters.py）：
    库存 quantity = 物理总持有（本脚本不改它）
    在售 on_sale_quantity = 该库存绑定的、且仍挂在售(on_sale/stop 且未软删)的煤炉商品件数
    待出 pending_outbound_qty = 非终态订单且未出库的出库明细合计（订单派生口径）
    可上架 listable_quantity = max(0, 库存 - 在售 - 待出)
并把 on_sale_items.counted_on_sale 置为：绑定到存在库存、未软删、status∈(on_sale,stop) 的为 1，其余为 0。

适用：全新库 / quantity 已是「物理总数」的库。本脚本可重复运行（幂等：直接覆盖为重算值，不累加）。
若 quantity 仍是旧「在售↔库存转移模型」下被扣减过的余量，请先运行 fix_inventory_total_quantity.py 还原。

用法（在 backend 目录下执行）：
    python scripts/migrate_inventory_counters.py            # 演练（dry-run）：仅打印将如何变化，不写库
    python scripts/migrate_inventory_counters.py --apply    # 实际写入数据库
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Set

# Windows 控制台默认非 UTF-8，重配 stdout 避免中文/日文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# 让脚本能 import 到 src 包（backend 为根）
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from src.db_manage.database import DatabaseManager  # noqa: E402
from src.db_manage.models.inventory import InventoryModel  # noqa: E402
from src.db_manage.models.on_sale_item import OnSaleItemModel  # noqa: E402
from src.db_manage.models.order_outbound_line import (  # noqa: E402
    TERMINAL_ORDER_STATUSES,
)
from src.use_mercari.inventory_counters import LISTED_STATUSES  # noqa: E402
from src.use_mercari.on_sale.on_sale_items_sync.inventory_qty import (  # noqa: E402
    _mercari_id_lookup_keys,
    _split_mercari_item_ids,
)


def _ensure_schema() -> None:
    """确保 on_sale_items.counted_on_sale 与 inventory.listable_quantity 列存在（按模型自动补列）。"""
    OnSaleItemModel.ensure_table_exists()
    InventoryModel.ensure_table_exists()


def _load_inventories(db: DatabaseManager) -> List[Dict]:
    rows = db.execute_query(
        """
        SELECT [id], [name], COALESCE([quantity], 0),
               COALESCE([on_sale_quantity], 0), COALESCE([pending_outbound_qty], 0),
               IFNULL([mercari_item_id], '')
        FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0
        ORDER BY [id] ASC
        """
    )
    out: List[Dict] = []
    for rid, name, qty, osq, pend, mids in rows or []:
        out.append(
            {
                "id": int(rid),
                "name": name,
                "quantity": int(qty or 0),
                "on_sale_quantity": int(osq or 0),
                "pending_outbound_qty": int(pend or 0),
                "item_ids": _split_mercari_item_ids(mids),
            }
        )
    return out


def _listed_item_id_keys(db: DatabaseManager) -> Set[str]:
    """返回仍挂在售（未软删 + status∈on_sale/stop）的煤炉商品 ID 的全部规范化键。"""
    status_ph = ",".join("?" * len(LISTED_STATUSES))
    rows = db.execute_query(
        f"""
        SELECT [item_id]
        FROM [on_sale_items]
        WHERE COALESCE([is_delete], 0) = 0
          AND TRIM(IFNULL([status], '')) IN ({status_ph})
        """,
        tuple(LISTED_STATUSES),
    )
    keys: Set[str] = set()
    for (item_id,) in rows or []:
        for k in _mercari_id_lookup_keys(str(item_id or "")):
            keys.add(k)
    return keys


def _pending_by_inventory(db: DatabaseManager) -> Dict[int, int]:
    """非终态订单 + 未出库的出库明细，按库存合计（与 refresh_inventory_pending_outbound_qty 同口径）。"""
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
    out: Dict[int, int] = {}
    for inv_id, q in rows or []:
        try:
            out[int(inv_id)] = max(0, int(q or 0))
        except (TypeError, ValueError):
            continue
    return out


def _existing_inventory_item_keys(invs: List[Dict]) -> Set[str]:
    """所有存在库存绑定的煤炉商品 ID 键集合（用于判定 listing 是否绑定到了存在库存）。"""
    keys: Set[str] = set()
    for inv in invs:
        for mid in inv["item_ids"]:
            for k in _mercari_id_lookup_keys(mid):
                keys.add(k)
    return keys


def run(apply: bool) -> None:
    db = DatabaseManager()
    _ensure_schema()

    invs = _load_inventories(db)
    listed_keys = _listed_item_id_keys(db)
    pending_map = _pending_by_inventory(db)
    inv_bound_keys = _existing_inventory_item_keys(invs)

    print(f"{'ID':>6}  {'名称':<20} {'原库存':>6} {'在售':>5} {'待出':>5}  ->  "
          f"{'新库存':>6} {'在售':>5} {'待出':>5}")
    print("-" * 90)

    total_changed = 0
    plan: List[Dict] = []
    for inv in invs:
        # 在售：该库存绑定的、仍挂在售的煤炉商品件数（出品 1 件 = 1）
        listed_count = 0
        seen: Set[str] = set()
        for mid in inv["item_ids"]:
            mid_keys = _mercari_id_lookup_keys(mid)
            sig = mid_keys[0] if mid_keys else mid
            if sig in seen:
                continue
            seen.add(sig)
            if any(k in listed_keys for k in mid_keys):
                listed_count += 1

        pend = int(pending_map.get(inv["id"], 0))
        new_on_sale = listed_count
        new_pending = pend
        # 新模型：quantity 为物理总持有，不在此变动；可上架 = max(0, 库存 - 在售 - 待出)
        new_listable = max(0, inv["quantity"] - new_on_sale - new_pending)

        changed = (
            new_on_sale != inv["on_sale_quantity"]
            or new_pending != inv["pending_outbound_qty"]
        )
        if changed:
            total_changed += 1
            name = (inv["name"] or "")[:20]
            print(f"{inv['id']:>6}  {name:<20} {inv['quantity']:>6} "
                  f"{inv['on_sale_quantity']:>5} {inv['pending_outbound_qty']:>5}  ->  "
                  f"{inv['quantity']:>6} {new_on_sale:>5} {new_pending:>5} (可上架 {new_listable})")
        plan.append(
            {
                "id": inv["id"],
                "on_sale_quantity": new_on_sale,
                "pending_outbound_qty": new_pending,
                "listable_quantity": new_listable,
            }
        )

    print("-" * 90)
    print(f"库存行共 {len(invs)} 条，将变更 {total_changed} 条。")

    # counted_on_sale 标记：绑定到存在库存、未软删、status∈(on_sale,stop) 的为 1，其余为 0
    status_ph = ",".join("?" * len(LISTED_STATUSES))
    rows = db.execute_query(
        f"""
        SELECT [item_id], COALESCE([is_delete], 0),
               TRIM(IFNULL([status], '')) IN ({status_ph}) AS listed
        FROM [on_sale_items]
        """,
        tuple(LISTED_STATUSES),
    )
    flag_to_set: Dict[str, int] = {}
    for item_id, is_delete, listed in rows or []:
        iid = str(item_id or "").strip()
        if not iid:
            continue
        bound = any(k in inv_bound_keys for k in _mercari_id_lookup_keys(iid))
        want = 1 if (int(is_delete or 0) == 0 and int(listed or 0) == 1 and bound) else 0
        flag_to_set[iid] = want
    counted_ones = sum(1 for v in flag_to_set.values() if v == 1)
    print(f"on_sale_items 共 {len(flag_to_set)} 条，其中将标记 counted_on_sale=1 的 {counted_ones} 条。")

    if not apply:
        print("\n[dry-run] 未写入数据库。确认无误后加 --apply 实际执行。")
        return

    for p in plan:
        db.execute_update(
            """
            UPDATE [inventory]
            SET [on_sale_quantity] = ?, [pending_outbound_qty] = ?, [listable_quantity] = ?
            WHERE [id] = ?
            """,
            (p["on_sale_quantity"], p["pending_outbound_qty"], p["listable_quantity"], p["id"]),
        )
    for iid, want in flag_to_set.items():
        db.execute_update(
            "UPDATE [on_sale_items] SET [counted_on_sale] = ? WHERE TRIM([item_id]) = TRIM(?)",
            (want, iid),
        )
    print(f"\n[apply] 已写入：inventory {len(plan)} 行，on_sale_items.counted_on_sale {len(flag_to_set)} 条。")


def main() -> None:
    parser = argparse.ArgumentParser(description="库存三栏计数器一次性对账迁移")
    parser.add_argument("--apply", action="store_true", help="实际写入数据库（缺省为 dry-run 演练）")
    args = parser.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
