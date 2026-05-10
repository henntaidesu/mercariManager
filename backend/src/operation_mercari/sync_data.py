# -*- coding: utf-8 -*-
"""
Mercari 数据同步调度层

提供统一的同步入口，供 API 层调用。
后续如需扩展更多同步类型（订单详情、评价等），在本文件中添加对应方法即可。
"""

from typing import Any, Dict, List, Optional, Tuple

from .get_order.get_history_order.get_history_list import (
    fetch_and_sync_history_orders,
)
from .get_order.get_in_progress_order.get_order_list import (
    fetch_and_sync_open_orders,
    fetch_open_order_items,
    _item_to_order_data,
    _upsert_order,
)
from .get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ..db_manage.models.meilu_account import MeiluAccountModel
from ..db_manage.models.order import OrderModel


def resolve_account_id_by_seller_id(seller_id_str: Optional[str]) -> Optional[int]:
    """
    根据 Mercari 卖家 ID（与订单 data_user 一致）查找用于请求的煤炉账号主键。
    仅匹配 status=active；找不到返回 None。
    """
    sid = (seller_id_str or "").strip()
    if not sid:
        return None
    rows = MeiluAccountModel.find_all(
        where="[seller_id] = ? AND [status] = ?",
        params=(sid, "active"),
        limit=1,
    )
    return rows[0].id if rows else None


def _resolve_account_and_seller(account_id: Optional[int]) -> Tuple[int, int]:
    """
    解析煤炉账号与卖家 ID。

    :return: (account_id, seller_id)
    """
    if account_id is not None:
        account = MeiluAccountModel.find_by_id(id=account_id)
        if not account:
            raise RuntimeError(f"未找到 ID={account_id} 的煤炉账号")
    else:
        records = MeiluAccountModel.find_all(
            where="[status] = ?",
            params=("active",),
            order_by="id ASC",
            limit=1,
        )
        if not records:
            raise RuntimeError("数据库中无可用的 active 状态煤炉账号")
        account = records[0]
        account_id = account.id

    seller_id = (str(account.seller_id or "")).strip()
    if not seller_id:
        raise RuntimeError(f"账号「{account.account_name}」未配置卖家ID，请先在账号管理中补充")
    if not seller_id.isdigit():
        raise RuntimeError(f"账号「{account.account_name}」的卖家ID格式错误（必须为纯数字）")

    return account_id, int(seller_id)


def history_sync_precheck(account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    「获取历史数据」前置校验：orders 表中若已有 data_user = 该卖家 ID 的记录，则不允许全量拉取。

    :return: allowed、existing_order_count、seller_id、message（供前端提示）
    """
    _, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))
    n = OrderModel.count(where="[data_user] = ?", params=(seller_key,))
    if n > 0:
        return {
            "allowed": False,
            "existing_order_count": n,
            "seller_id": seller_key,
            "message": (
                f"订单表中已有该卖家（data_user={seller_key}）的 {n} 条记录，"
                "不允许重复执行「获取历史数据」。请使用订单页的增量同步或刷新。"
            ),
        }
    return {
        "allowed": True,
        "existing_order_count": 0,
        "seller_id": seller_key,
        "message": "本地尚无该卖家的订单，可执行全量拉取。",
    }


def sync_open_orders(
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    同步 Mercari 订单到本地订单管理表（「获取历史数据」）：
    1）WebDriver 打开 ``/mypage/listings/in_progress``，MITM 截获 trading 列表；
    2）WebDriver 打开 ``/mypage/listings/completed``，MITM 截获 sold_out 列表。

    若 orders 中已存在 data_user 与当前卖家 ID 一致的任意记录，则拒绝执行（与 history_sync_precheck 一致）。

    :param account_id: 指定使用的煤炉账号 ID；为 None 时自动选取第一个 active 账号。
    :return: 合并统计 + 分项 trading / history，便于前端展示。
    :raises RuntimeError: 账号不可用或网络请求失败时抛出。
    """
    aid, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))
    if OrderModel.count(where="[data_user] = ?", params=(seller_key,)) > 0:
        raise RuntimeError(
            "订单表中已存在该卖家的订单数据（data_user 与卖家 ID 一致），禁止重复执行「获取历史数据」。"
        )
    trading = fetch_and_sync_open_orders(seller_id=sid, account_id=aid)
    history = fetch_and_sync_history_orders(seller_id=sid, account_id=aid)

    t_ic = trading.get("total_item_count")
    if t_ic is None:
        t_ic = trading["total"]
    h_ic = history.get("total_item_count")
    if h_ic is None:
        h_ic = history["total"]

    return {
        "trading": trading,
        "history": history,
        "inserted": trading["inserted"] + history["inserted"],
        "updated": trading["updated"] + history["updated"],
        "skipped": trading["skipped"] + history["skipped"],
        "total": trading["total"] + history["total"],
        "total_item_count": t_ic + h_ic,
        "errors": trading["errors"] + history["errors"],
        "info_enriched": trading.get("info_enriched", 0) + history.get("info_enriched", 0),
        "info_errors": trading.get("info_errors", []) + history.get("info_errors", []),
    }


def sync_new_data(account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    增量同步出售中订单：WebDriver 打开取引中一覧 + MITM 截获 trading 列表；按本地水印只对尚未入库的 item 入库；
    入库顺序与列表顺序相反（倒序入库）。每条成功写入后 ``apply_item_info_to_order`` 打开取引页截获详情并回填扩展字段。

    - 仅处理当前页 trading 数据（与全量 sync_open_orders 中 open 段一致）。
    - 依赖订单表 data_user 与当前卖家 ID 一致；筛选水印时也按 data_user 限定。
    """
    aid, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))

    latest_rows = OrderModel.find_all(
        where="[data_user] = ?",
        params=(seller_key,),
        order_by="COALESCE([order_updated_at], [order_date]) DESC, [id] DESC",
        limit=1,
    )
    watermark_order_no = latest_rows[0].order_no if latest_rows else None

    items, meta = fetch_open_order_items(seller_id=sid, account_id=aid)

    raw_ids: List[str] = []
    for it in items:
        oid = it.get("id")
        if oid is not None and str(oid).strip():
            raw_ids.append(str(oid).strip())
    uniq_ids = list(dict.fromkeys(raw_ids))

    db = OrderModel().db
    existing_nos: set = set()
    if uniq_ids:
        placeholders = ",".join(["?"] * len(uniq_ids))
        sql = f"SELECT [order_no] FROM [orders] WHERE [order_no] IN ({placeholders})"
        existing_nos = {r[0] for r in db.execute_query(sql, tuple(uniq_ids))}

    pending: List[Dict[str, Any]] = [
        it for it in items if str(it.get("id", "")).strip() not in existing_nos
    ]
    to_save = list(reversed(pending))

    stats: Dict[str, Any] = {
        "watermark_order_no": watermark_order_no,
        "api_item_count": len(items),
        "pending_new": len(pending),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "info_enriched": 0,
        "info_errors": [],
        "has_next": meta.get("has_next", False),
        "total_item_count": meta.get("total_item_count", len(items)),
    }

    for item in to_save:
        iid = item.get("id")
        try:
            order_data = _item_to_order_data(item, seller_id=sid)
            result = _upsert_order(order_data)
            stats[result] += 1
        except Exception as exc:
            stats["errors"].append({"item_id": item.get("id"), "error": str(exc)})
            continue

        # 与 fetch_and_sync_open_orders 一致：入库后必须 transaction_evidences/get（get_order_info）回填扩展字段
        if result == "skipped" or not iid:
            continue
        try:
            err = apply_item_info_to_order(str(iid), account_id=aid)
            if err is None:
                stats["info_enriched"] += 1
            else:
                stats["info_errors"].append({"item_id": iid, "error": err})
        except Exception as exc:
            stats["info_errors"].append({"item_id": iid, "error": f"info_exception:{exc}"})

    print(
        f"[sync_new_data] watermark_order_no={watermark_order_no!r} "
        f"api_items={len(items)} pending_new={len(pending)} "
        f"inserted={stats['inserted']} updated={stats['updated']} "
        f"info_ok={stats['info_enriched']}"
    )
    return stats


def batch_refresh_orders_info(account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    从订单表选出未完成且 data_user 非空的行，逐条 WebDriver 打开取引页 + MITM 截获 transaction_evidences/get（与列表「刷新」相同）。

    :param account_id: 指定煤炉账号时，仅刷新该账号 seller_id 与 orders.data_user 一致的行；
                       不传则扫描库内所有符合条件的订单（逐条按 data_user 解析账号）。
    """
    seller_filter: Optional[str] = None
    if account_id is not None:
        acc = MeiluAccountModel.find_by_id(id=account_id)
        if not acc:
            raise RuntimeError(f"未找到 ID={account_id} 的煤炉账号")
        seller_filter = (str(acc.seller_id or "")).strip()
        if not seller_filter:
            raise RuntimeError(f"账号「{acc.account_name}」未配置 seller_id")

    pairs = OrderModel.find_for_batch_info_refresh(seller_id_filter=seller_filter)
    stats: Dict[str, Any] = {
        "total": len(pairs),
        "ok": 0,
        "skipped_no_account": 0,
        "failed": [],
    }

    for order_no, data_user in pairs:
        aid = resolve_account_id_by_seller_id(data_user)
        if aid is None:
            stats["skipped_no_account"] += 1
            continue
        err = apply_item_info_to_order(
            order_no, account_id=aid, expected_seller_id=data_user
        )
        if err:
            stats["failed"].append({"order_no": order_no, "error": err})
        else:
            stats["ok"] += 1

    return stats
