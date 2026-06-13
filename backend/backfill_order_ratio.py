# -*- coding: utf-8 -*-
"""
一次性回填：为所有订单计算并持久化各出库行的 goods_ratio / ratio_price / ratio_unit_price，
使订单列表 / 二级明细 / 统计 / 包材拆分改为读库，不再每次请求实时扫描 on_sale_items。

会先 init_database() 确保 order_outbound_lines 已补齐三个新列，再逐单重算写库。

用法：
    cd backend
    python backfill_order_ratio.py
"""
import sys

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.db_manage.db_manager import init_database
from src.db_manage.database import DatabaseManager
from src.use_web.orders.units.order_goods_ratio import recompute_and_store_order_ratio


def main():
    if not init_database():
        print("[错误] 数据库初始化失败，已中止回填")
        return

    db = DatabaseManager()
    rows = db.execute_query("SELECT [order_no] FROM [orders] ORDER BY [order_no]")
    total = len(rows)
    done = 0
    for r in rows:
        ono = str(r[0] or "").strip()
        if not ono:
            continue
        recompute_and_store_order_ratio(ono)
        done += 1
        if done % 50 == 0:
            print(f"  进度 {done}/{total}")

    n_line = db.execute_query(
        "SELECT COUNT(*) FROM [order_outbound_lines] WHERE [ratio_price] IS NOT NULL"
    )[0][0]
    print(f"完成：处理订单 {done}/{total}，已写入 ratio_price 的出库行 {n_line} 条。")


if __name__ == "__main__":
    main()
