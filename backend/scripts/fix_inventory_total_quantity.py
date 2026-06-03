# -*- coding: utf-8 -*-
"""一次性修正脚本：把 inventory.quantity 从「可售余量」恢复为「物理总持有」，并初始化 listable_quantity。

背景：早前 migrate_inventory_counters.py 把 quantity 改写成了「原 quantity − 在售 − 待出」（在售↔库存
转移模型）。现模型改为：
    库存 quantity = 物理总持有（上架/下架不改它）
    可上架 listable_quantity = max(0, 库存 − 在售 − 待出)
因此需要把 quantity 还原为总数：
    quantity_new = 当前 quantity + 在售 + 待出
    listable_new = max(0, quantity_new − 在售 − 待出)  （= 还原前的 quantity）

用法（在 backend 目录下执行）：
    python scripts/fix_inventory_total_quantity.py            # 演练（dry-run）
    python scripts/fix_inventory_total_quantity.py --apply    # 实际写入数据库

注意：
    · 仅在「已执行过 migrate_inventory_counters.py --apply」的库上运行一次。
    · 不幂等：重复 --apply 会把在售/待出再次累加进 quantity。请仅执行一次，先备份 mercariDB.db。
    · 如果是全新库（从未跑过旧迁移、quantity 本就是总数），请改用 migrate_inventory_counters.py。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from src.db_manage.database import DatabaseManager  # noqa: E402
from src.db_manage.models.inventory import InventoryModel  # noqa: E402


def run(apply: bool) -> None:
    db = DatabaseManager()
    # 确保 listable_quantity 列存在（按模型定义自动补列）
    InventoryModel.ensure_table_exists()

    rows = db.execute_query(
        """
        SELECT [id], [name], COALESCE([quantity], 0),
               COALESCE([on_sale_quantity], 0), COALESCE([pending_outbound_qty], 0)
        FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0
        ORDER BY [id] ASC
        """
    )

    print(f"{'ID':>6}  {'名称':<22} {'原库存':>6} {'在售':>5} {'待出':>5}  ->  "
          f"{'总库存':>6} {'可上架':>6}")
    print("-" * 80)

    plan: List[Dict] = []
    changed = 0
    for rid, name, q, os_q, pend in rows or []:
        rid = int(rid)
        q = int(q or 0)
        os_q = int(os_q or 0)
        pend = int(pend or 0)
        q_new = q + os_q + pend
        listable_new = max(0, q_new - os_q - pend)
        plan.append({"id": rid, "quantity": q_new, "listable": listable_new})
        if q_new != q:
            changed += 1
            nm = (name or "")[:22]
            print(f"{rid:>6}  {nm:<22} {q:>6} {os_q:>5} {pend:>5}  ->  "
                  f"{q_new:>6} {listable_new:>6}")

    print("-" * 80)
    print(f"库存行共 {len(plan)} 条，quantity 将变更 {changed} 条。")

    if not apply:
        print("\n[dry-run] 未写入数据库。确认无误后加 --apply 实际执行。")
        return

    for p in plan:
        db.execute_update(
            "UPDATE [inventory] SET [quantity] = ?, [listable_quantity] = ? WHERE [id] = ?",
            (p["quantity"], p["listable"], p["id"]),
        )
    print(f"\n[apply] 已写入：inventory {len(plan)} 行（quantity 还原为总数，listable_quantity 初始化）。")


def main() -> None:
    parser = argparse.ArgumentParser(description="把 quantity 还原为物理总数并初始化 listable_quantity")
    parser.add_argument("--apply", action="store_true", help="实际写入数据库（缺省为 dry-run 演练）")
    args = parser.parse_args()
    run(apply=bool(args.apply))


if __name__ == "__main__":
    main()
