# -*- coding: utf-8 -*-
"""雅虎「購入者が受取評価しました。これで取引完了です」通知 → 订单置为已完成。

雅虎的「待评价 → 已完成」只写在交易页上，而读交易页是一件一次页面加载；但这条状态变化
本来就会以通知推给卖家，而且通知带着 ``itemId``（雅虎一件商品只卖一份，它**就是**本地的
``orders.order_no``）。所以完成状态改由通知驱动，订单同步不必再为已成交的订单开页面。

通知长这样（实测 9/9 条措辞完全一致）::

    {"type": "rberr", "title": "取引完了",
     "content": "購入者が受取評価しました。これで取引完了です", "itemId": "z…"}

判定用**措辞**而不是那个 ``type``：``rberr`` 是个没有可查资料的不透明码，只在一个账号的
9 条样本上见过，雅虎哪天拿它表示别的意思无从得知；措辞则是雅虎显示给卖家的原文。并且要求
「受取評価」与「取引完了」两处同时出现——宁可漏判（订单留在待评价，「更新状态」按钮照样
能纠正），也不能把别的通知错认成交易完成：订单状态会驱动出库与结算，认错比漏判严重得多。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

#: 两处措辞都命中才算「买家已受取评价、交易完成」
_COMPLETION_MARKERS: Tuple[str, ...] = ("受取評価", "取引完了")

#: SQL 侧的粗筛（把候选缩到几条），严格判定仍在 Python 里做
_COMPLETION_LIKE = "%受取評価%"


def _is_completion_text(text: str) -> bool:
    t = str(text or "")
    return all(marker in t for marker in _COMPLETION_MARKERS)


def _notice_text(message: Any, args_json: Any) -> str:
    """通知里可用于判定的全部文本。

    ``yahoo_notice_to_row`` 存进 ``message`` 的是 ``content or title``，而这条通知的措辞
    在 **title** 上，所以必须把原始 JSON 里的 title / content 一起算进来。
    """
    parts: List[str] = [str(message or "")]
    try:
        raw = json.loads(args_json) if args_json else None
    except (TypeError, ValueError):
        raw = None
    if isinstance(raw, dict):
        parts.append(str(raw.get("title") or ""))
        parts.append(str(raw.get("content") or ""))
    return "\n".join(parts)


def completed_item_ids() -> Dict[str, Optional[int]]:
    """已入库的雅虎通知里判定为「交易完成」的 商品ID → 通知时间（毫秒，可能为空）。"""
    from ...db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT [item_id], [mercari_created], [message], [args_json] FROM [notifications] "
        "WHERE TRIM(IFNULL([platform], '')) = 'yahoo' "
        "AND IFNULL(TRIM([item_id]), '') != '' "
        "AND (IFNULL([message], '') LIKE ? OR IFNULL([args_json], '') LIKE ?)",
        (_COMPLETION_LIKE, _COMPLETION_LIKE),
    ) or []

    out: Dict[str, Optional[int]] = {}
    for r in rows:
        item_id = str(r[0] or "").strip()
        if not item_id or not _is_completion_text(_notice_text(r[2], r[3])):
            continue
        created = int(r[1]) if r[1] else None
        # 同一商品若有多条，取最早的一条——那才是买家评价的时刻
        if item_id in out:
            prev = out[item_id]
            if created is not None and (prev is None or created < prev):
                out[item_id] = created
        else:
            out[item_id] = created
    return out


def apply_yahoo_receipt_notices() -> Dict[str, Any]:
    """把收到「受取評価 → 取引完了」通知的雅虎订单置为已完成。

    幂等：已是终态的订单一律不动，所以重复调用只有第一次真正写库。终态集合直接取
    ``OrderModel._STATUSES_SKIP_BATCH_INFO``——「更新状态」跳过哪些订单、这里就认哪些是
    已结清，两处各写一份迟早会各改各的。

    通知先到、订单还没同步进来的情况直接跳过：通知接口每次返回全量，下一次同步会补上。
    """
    from ...db_manage.models.orders.order.model import OrderModel

    stats: Dict[str, Any] = {"matched": 0, "completed": 0, "completed_order_nos": []}
    targets = completed_item_ids()
    stats["matched"] = len(targets)
    if not targets:
        return stats

    settled = set(OrderModel._STATUSES_SKIP_BATCH_INFO)
    for order_no, created_ms in targets.items():
        rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not rows:
            continue
        order = rows[0]
        platform = (str(getattr(order, "platform", "") or "").strip().lower() or "mercari")
        if platform != "yahoo":
            continue
        if str(getattr(order, "status", "") or "") in settled:
            continue
        order.status = "done"
        # completed_at 口径与煤炉一致：状态变 done 的那一刻，写一次不覆盖。
        # 雅虎交易页给不出这个时刻，通知的 createDate 就是买家评价的时间。
        if not getattr(order, "completed_at", None):
            order.completed_at = int(created_ms // 1000) if created_ms else int(time.time())
        if order.save():
            stats["completed"] += 1
            stats["completed_order_nos"].append(order_no)
        else:
            log.warning("[yahoo_notices] 订单 %s 置为已完成失败", order_no)

    if stats["completed"]:
        log.info(
            "[yahoo_notices] 受取評価通知 → %d 笔订单置为已完成：%s",
            stats["completed"], stats["completed_order_nos"],
        )
    return stats
