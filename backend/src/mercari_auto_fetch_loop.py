# -*- coding: utf-8 -*-
"""
煤炉账号「自动数据获取」后台调度。

开启且 status=active 的账号，按 fetch_interval 节流；在账号配置的子任务中按需执行（与同账号 run_mercari_serial_async 串行）：
- auto_fetch_order_list → sync_new_data（订单页「更新列表」）
- auto_fetch_on_sale → sync_on_sale_items_from_mercari（在售页「从煤炉同步」）
- auto_fetch_todos → sync_todos_from_mercari（待办页「从煤炉同步」）
- auto_fetch_notifications → sync_notifications_from_mercari（通知页「从煤炉同步」）

环境变量：
- MERCARI_AUTO_FETCH：设为 0/false/off 关闭本循环（默认开启）
- MERCARI_AUTO_FETCH_TICK_SEC：轮询间隔秒（默认 60，最小 15）
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .db_manage.models.mercari_account import MercariAccountModel
from .db_manage.models.system_log import SystemLogModel
from .use_mercari.get_notifications.notification_sync import sync_notifications_from_mercari
from .use_mercari.get_to_du_list.todolist_sync import sync_todos_from_mercari
from .use_mercari.on_sale_items_sync import sync_on_sale_items_from_mercari
from .use_mercari.sync_data import sync_new_data
from .use_mercari.sync_lock import LABEL_AUTO, end as sync_lock_end, try_begin as sync_lock_try_begin
from .web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async

log = logging.getLogger(__name__)


class _AutoFetchTaskError(Exception):
    """携带「失败时正在运行的子任务键」的异常，用于日志记录具体是哪个方法出错。"""

    def __init__(self, task_key: str, original: BaseException) -> None:
        self.task_key = task_key
        self.original = original
        super().__init__(str(original))

_INTERVAL_SEC = {
    "15": 15 * 60,
    "30": 30 * 60,
    "60": 60 * 60,
    "3h": 3 * 3600,
    "6h": 6 * 3600,
    "10": 10 * 60,
    "12h": 12 * 3600,
    "24h": 24 * 3600,
}


def _interval_seconds(iv: Optional[str]) -> int:
    key = (iv or "").strip()
    return _INTERVAL_SEC.get(key, 30 * 60)


def _parse_last_at(raw: Optional[str]) -> Optional[datetime]:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_row_is_open(v) -> bool:
    if v is True:
        return True
    if v is False or v is None:
        return False
    try:
        return bool(int(v))
    except (TypeError, ValueError):
        return False


def _parse_hhmm_to_minutes(raw: Optional[str]) -> Optional[int]:
    s = (raw or "").strip()
    if not s or ":" not in s:
        return None
    hh, _, mm = s.partition(":")
    try:
        h = int(hh)
        m = int(mm[:2]) if mm else 0
    except ValueError:
        return None
    if not (0 <= h <= 23) or not (0 <= m <= 59):
        return None
    return h * 60 + m


def _account_in_pause_window(item: MercariAccountModel, now_local: datetime) -> bool:
    """根据账号 pause_start_time / pause_end_time（本地时间 HH:MM）判断当前是否处于暂停期。

    - 两个字段任一为空：不暂停
    - start == end：视为无效，不暂停
    - start < end：当日窗口 [start, end)
    - start > end：跨日窗口 [start, 24:00) ∪ [00:00, end)
    """
    start = _parse_hhmm_to_minutes(getattr(item, "pause_start_time", None))
    end = _parse_hhmm_to_minutes(getattr(item, "pause_end_time", None))
    if start is None or end is None or start == end:
        return False
    cur = now_local.hour * 60 + now_local.minute
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _any_auto_task_enabled(item: MercariAccountModel) -> bool:
    return (
        _normalize_row_is_open(getattr(item, "auto_fetch_order_list", 0))
        or _normalize_row_is_open(getattr(item, "auto_fetch_on_sale", 0))
        or _normalize_row_is_open(getattr(item, "auto_fetch_todos", 0))
        or _normalize_row_is_open(getattr(item, "auto_fetch_notifications", 0))
    )


def _account_due(item: MercariAccountModel, now: datetime) -> bool:
    if not _normalize_row_is_open(item.is_open):
        return False
    if not _any_auto_task_enabled(item):
        return False
    iv = (item.fetch_interval or "").strip()
    if not iv:
        return False
    last = _parse_last_at(getattr(item, "auto_fetch_last_at", None))
    if last is None:
        return True
    elapsed = (now - last).total_seconds()
    return elapsed >= _interval_seconds(iv)


async def _run_auto_fetch_for_account(aid: int, item: MercariAccountModel) -> Dict[str, Any]:
    """执行账号本轮各子任务并收集各自返回的 stats（用于系统日志汇总）。"""
    li = _normalize_row_is_open(getattr(item, "auto_fetch_order_list", 0))
    os_ = _normalize_row_is_open(getattr(item, "auto_fetch_on_sale", 0))
    td = _normalize_row_is_open(getattr(item, "auto_fetch_todos", 0))
    nt = _normalize_row_is_open(getattr(item, "auto_fetch_notifications", 0))
    results: Dict[str, Any] = {}
    if not (li or os_ or td or nt):
        return results

    async def _body():
        # (子任务键, 是否启用, 实际调用)；按顺序串行执行，失败时携带子任务键抛出便于日志定位
        plan = (
            ("order_list", li, lambda: sync_new_data(account_id=aid)),
            ("on_sale", os_, lambda: sync_on_sale_items_from_mercari(account_id=aid)),
            ("todos", td, lambda: sync_todos_from_mercari(account_id=aid)),
            ("notifications", nt, lambda: sync_notifications_from_mercari(account_id=aid)),
        )
        for key, enabled, call in plan:
            if not enabled:
                continue
            try:
                results[key] = await call()
            except Exception as exc:
                raise _AutoFetchTaskError(key, exc) from exc

    await run_mercari_serial_async(queue_key_for_mercari_account(aid), _body)
    return results


_AUTO_FETCH_TASK_LABELS = {
    "order_list": "订单",
    "on_sale": "在售",
    "todos": "待办",
    "notifications": "通知",
}


def _stats_error_count(stats: Any) -> int:
    if not isinstance(stats, dict):
        return 0
    n = 0
    for key in ("errors", "info_errors"):
        v = stats.get(key)
        if isinstance(v, (list, tuple)):
            n += len(v)
    return n


def _summarize_auto_fetch(results: Dict[str, Any]) -> Tuple[str, str]:
    """把各子任务 stats 汇总为一条人类可读消息与级别（有错误→warning）。"""
    parts: List[str] = []
    has_err = False
    for key in ("order_list", "on_sale", "todos", "notifications"):
        if key not in results:
            continue
        stats = results[key]
        label = _AUTO_FETCH_TASK_LABELS[key]
        if isinstance(stats, dict):
            seg = f"{label} 新增{stats.get('inserted', 0)}/更新{stats.get('updated', 0)}"
            err_n = _stats_error_count(stats)
            if err_n:
                has_err = True
                seg += f"/错误{err_n}"
            parts.append(seg)
        else:
            parts.append(f"{label} -")
    message = "；".join(parts) if parts else "无启用的子任务"
    return message, ("warning" if has_err else "info")


def _mark_last_at(aid: int) -> None:
    item = MercariAccountModel.find_by_id(id=aid)
    if not item:
        return
    item.auto_fetch_last_at = _now_iso()
    item.save()


async def run_mercari_auto_fetch_tick() -> None:
    raw = (os.environ.get("MERCARI_AUTO_FETCH") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return

    now = datetime.now(timezone.utc)
    now_local = datetime.now()
    rows = MercariAccountModel.find_all(
        where="[is_open] = 1 AND [status] = ?",
        params=("active",),
    )
    for item in rows:
        aid = getattr(item, "id", None)
        if aid is None:
            continue
        try:
            if not _account_due(item, now):
                continue
            if _account_in_pause_window(item, now_local):
                log.debug(
                    "[mercari_auto_fetch] 账号 id=%s 当前处于暂停时间段（%s - %s），跳过",
                    aid,
                    getattr(item, "pause_start_time", None),
                    getattr(item, "pause_end_time", None),
                )
                continue
            sid = str(item.seller_id or "").strip()
            if not sid:
                log.warning("[mercari_auto_fetch] 账号 id=%s 已开启自动获取但未配置 seller_id，跳过", aid)
                continue
            if not _any_auto_task_enabled(item):
                continue
            # 全局同步锁：若有用户发起的同步（全量/各页）正在进行，本轮跳过该账号，下个 tick 再试
            lock_token = sync_lock_try_begin("auto", LABEL_AUTO)
            if lock_token is None:
                log.info(
                    "[mercari_auto_fetch] 账号 id=%s 跳过本轮：有用户发起的同步正在进行", aid
                )
                continue
            try:
                log.info("[mercari_auto_fetch] 开始账号 id=%s seller_id=%s", aid, sid)
                results = await _run_auto_fetch_for_account(int(aid), item)
                _mark_last_at(int(aid))
                msg, level = _summarize_auto_fetch(results)
                SystemLogModel.add(
                    category="auto_fetch",
                    level=level,
                    account_id=int(aid),
                    account_name=getattr(item, "account_name", None),
                    message=msg,
                    detail=results,
                )
                log.info("[mercari_auto_fetch] 完成账号 id=%s", aid)
            finally:
                sync_lock_end(lock_token)
        except _AutoFetchTaskError as exc:
            label = _AUTO_FETCH_TASK_LABELS.get(exc.task_key, exc.task_key)
            log.exception(
                "[mercari_auto_fetch] 账号 id=%s 子任务[%s]失败", aid, label
            )
            SystemLogModel.add(
                category="auto_fetch",
                level="error",
                account_id=int(aid) if aid is not None else None,
                account_name=getattr(item, "account_name", None),
                message=f"自动获取异常[{label}]：{exc.original}",
                detail={
                    "task": exc.task_key,
                    "task_label": label,
                    "error": str(exc.original),
                },
            )
        except Exception as exc:
            log.exception("[mercari_auto_fetch] 账号 id=%s 本轮失败", aid)
            SystemLogModel.add(
                category="auto_fetch",
                level="error",
                account_id=int(aid) if aid is not None else None,
                account_name=getattr(item, "account_name", None),
                message=f"自动获取异常：{exc}",
            )


def _tick_seconds() -> int:
    try:
        n = int((os.environ.get("MERCARI_AUTO_FETCH_TICK_SEC") or "60").strip() or "60")
    except ValueError:
        n = 60
    return max(15, n)


async def mercari_auto_fetch_loop() -> None:
    sec = _tick_seconds()
    log.info("[mercari_auto_fetch] 后台循环已启动，tick=%ss", sec)
    while True:
        try:
            await run_mercari_auto_fetch_tick()
        except Exception:
            log.exception("[mercari_auto_fetch] tick 外层异常")
        await asyncio.sleep(sec)
