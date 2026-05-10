# -*- coding: utf-8 -*-
"""
煤炉浏览器任务串行队列：同一账号（meilu_{id}）或全局批量任务在同一时刻只执行一个，
避免并发点击导致同一 Edge profile / MITM 流程互相打断。

实现：每个队列键对应 ``ThreadPoolExecutor(max_workers=1)``，提交的任务按 FIFO 执行；
不同账号使用不同 executor，可并行。
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, Optional, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

_executors: Dict[str, ThreadPoolExecutor] = {}
_executors_lock = threading.Lock()

# 未指定 account_id 的订单批量刷新等「跨账号」任务共用此键，全局串行
GLOBAL_QUEUE_KEY = "meilu_serial_global"


def queue_key_for_meilu_account(account_id: int) -> str:
    return f"meilu_{int(account_id)}"


def default_task_timeout_sec() -> Optional[float]:
    raw = (os.environ.get("MEILU_BROWSER_TASK_TIMEOUT_SEC") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _executor_for(queue_key: str) -> ThreadPoolExecutor:
    with _executors_lock:
        ex = _executors.get(queue_key)
        if ex is None:
            safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in queue_key)[:40]
            ex = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"mq_{safe_name}_",
            )
            _executors[queue_key] = ex
        return ex


def run_meilu_serial(
    queue_key: str,
    fn: Callable[[], T],
    *,
    timeout_sec: Optional[float] = None,
) -> T:
    """
    在指定队列键下串行执行 ``fn``（先进先出）。

    :param queue_key: 通常 ``queue_key_for_meilu_account(account_id)`` 或 ``GLOBAL_QUEUE_KEY``
    :param timeout_sec: 等待结果超时秒数；默认读环境变量 ``MEILU_BROWSER_TASK_TIMEOUT_SEC``，未设置则无超时
    """
    ex = _executor_for(queue_key)
    fut = ex.submit(fn)
    to = timeout_sec if timeout_sec is not None else default_task_timeout_sec()
    try:
        return fut.result(timeout=to)
    except FuturesTimeout as exc:
        raise TimeoutError(
            f"煤炉浏览器任务超时（队列键={queue_key}，timeout_sec={to}）"
        ) from exc


def resolve_meilu_account_id(account_id: Optional[int]) -> int:
    """与 ``sync_new_data`` 等一致：解析最终使用的煤炉账号主键。"""
    from ..operation_mercari.sync_data import _resolve_account_and_seller

    aid, _ = _resolve_account_and_seller(account_id)
    return int(aid)


def shutdown_serial_executors(*, wait: bool = False) -> None:
    """进程退出时调用，避免遗留线程（wait=False 更快停机）。"""
    with _executors_lock:
        for key, ex in list(_executors.items()):
            try:
                ex.shutdown(wait=wait)
            except Exception:
                pass
            log.debug("serial executor shutdown: %s", key)
        _executors.clear()
