# -*- coding: utf-8 -*-
"""雅虎交易详情批量预缓存。

待办同步后，为「待发货 / 待回复」且尚无交易详情缓存的待办逐条静默补抓交易页，使前端
「处理」面板打开即有缓存可用。不做的话每打开一条都要现开一次浏览器读页面（数秒空转），
而且雅虎的发货表单可选项（サイズ / 発送場所）只有交易页知道，前端在抓完之前连表单都渲染不出来。

与煤炉 ``use_mercari/get_to_du_list/transaction_detail/precache.py`` 同一套收敛闸门，并
**共用**它的失败计数列（``todo_items.detail_fetch_failures``）、上限常量与单次条数上限：
两边抢的是同一条全局串行 worker，各设一套阈值只会让「一次同步最多占多久」不可预测。

**必须在该账号的串行队列内调用**：本函数不获取队列锁，直接复用已打开的浏览器会话
（与 ``fetch_yahoo_todo_detail`` 一致）。单条失败仅记录、不抛出。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from ...db_manage.database import DatabaseManager
from ...use_mercari.get_to_du_list.transaction_detail._cache import (
    PRECACHE_MAX_FAILURES,
    note_detail_fetch_failure,
)
from ...use_mercari.get_to_du_list.transaction_detail.precache import precache_max_per_run
from ...use_mercari.sync.sync_progress import make_sync_reporter
from .todo_sync import YAHOO_WAIT_REPLY_KIND, YAHOO_WAIT_SHIPPING_KIND

log = logging.getLogger(__name__)

#: 只有这两个 kind 背后有交易页；未知类型（``Yahoo:{type}``）只展示，开页面必然抓不到东西
_DETAIL_KINDS = (YAHOO_WAIT_SHIPPING_KIND, YAHOO_WAIT_REPLY_KIND)


def list_uncached_yahoo_todo_ids(
    account_id: int, *, limit: Optional[int] = None
) -> List[int]:
    """某账号下尚无交易详情缓存的雅虎待办 id（按最近更新优先）。

    判定「无缓存」：``detail_synced_at IS NULL``（抓取成功才会写）。缺 ``item_id`` 的行排除
    ——雅虎交易页只能按商品 ID 打开。连续失败 ``PRECACHE_MAX_FAILURES`` 次的行退出候选集合，
    否则一条永远抓不出来的待办（交易已结束、页面改版）会被**每个同步 tick** 重抓一次。
    """
    kind_ph = ",".join(["?"] * len(_DETAIL_KINDS))
    sql = (
        f"SELECT [id] FROM [todo_items] "
        f"WHERE [account_id] = ? AND TRIM(IFNULL([platform], '')) = 'yahoo' "
        f"AND COALESCE([is_delete], 0) = 0 "
        f"AND [detail_synced_at] IS NULL "
        f"AND COALESCE([detail_fetch_failures], 0) < ? "
        f"AND [item_id] IS NOT NULL AND TRIM([item_id]) <> '' "
        f"AND [kind] IN ({kind_ph}) "
        f"ORDER BY [mercari_updated] DESC"
    )
    params = (int(account_id), int(PRECACHE_MAX_FAILURES), *_DETAIL_KINDS)
    if limit is not None and int(limit) > 0:
        sql += f" LIMIT {int(limit)}"
    try:
        rows = DatabaseManager().execute_query(sql, params)
    except Exception as exc:  # noqa: BLE001 查询失败只是这轮不预缓存
        log.warning("[yahoo_trade] 查询未缓存待办失败 account_id=%s：%s", account_id, exc)
        return []
    return [int(r[0]) for r in rows or [] if r and r[0] is not None]


async def precache_uncached_yahoo_todo_details(
    account_id: int, *, progress_job_id: Optional[str] = None
) -> Tuple[int, int]:
    """为该账号无缓存的雅虎待办按序补抓交易详情，返回 ``(成功条数, 失败条数)``。"""
    from .trade_actions import fetch_yahoo_todo_detail

    limit = precache_max_per_run()
    todo_ids = list_uncached_yahoo_todo_ids(int(account_id), limit=limit)
    if not todo_ids:
        return 0, 0

    report = make_sync_reporter(progress_job_id)
    total = len(todo_ids)
    log.info(
        "[yahoo_trade] 交易详情预缓存 account_id=%s 本次 %d 条（单次上限 %d）",
        account_id, total, limit,
    )

    fetched = 0
    failed = 0
    for idx, tid in enumerate(todo_ids, start=1):
        report("precache_detail", f"补抓交易详情（{idx}/{total}）…")
        try:
            await fetch_yahoo_todo_detail(int(tid))
            fetched += 1
        except Exception as exc:  # noqa: BLE001 单条失败不阻断其余
            failed += 1
            n = note_detail_fetch_failure(int(tid))
            if n >= PRECACHE_MAX_FAILURES:
                log.warning(
                    "[yahoo_trade] 待办 %s 交易详情已连续失败 %d 次，不再自动重抓"
                    "（仍可在详情面板手动「刷新抓取」）：%s",
                    tid, n, exc,
                )
            else:
                log.warning(
                    "[yahoo_trade] 交易详情预缓存失败 todo_id=%s（第 %d/%d 次）：%s",
                    tid, n, PRECACHE_MAX_FAILURES, exc,
                )
    return fetched, failed
