# -*- coding: utf-8 -*-
"""全局出品锁（进程内、跨请求/跨用户共享）。

同一时刻只允许一个出品自动化在执行（手动「出品」与自动补挂 auto_relist 共用）：
- HTTP 手动出品入口：``wait=False`` → 已被占用时抛 ``ListingBusyError``（入口转 409）；
- 自动补挂（后台任务）：``wait=True`` → 排队等待获取，不丢任务。

独立无头出品 profile（``mercari_{id}__listing``）同一时刻只能被一个 Edge 进程占用，
本锁同时保证该 profile 不被并发打开。进程重启即清空（内存态）。
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Optional

_lock = asyncio.Lock()
_holder: Optional[Dict[str, object]] = None


class ListingBusyError(RuntimeError):
    """已有其他出品在进行（``wait=False`` 时抛出，HTTP 入口转 409）。"""

    def __init__(self, label_zh: str) -> None:
        self.label_zh = label_zh
        super().__init__(f"{label_zh}，请稍候再试")


def status() -> Dict[str, object]:
    """当前出品锁状态：``{locked, label_zh, started_at}``。"""
    if not _lock.locked() or _holder is None:
        return {"locked": False, "label_zh": None, "started_at": None}
    return {
        "locked": True,
        "label_zh": _holder.get("label_zh"),
        "started_at": _holder.get("started_at"),
    }


@asynccontextmanager
async def hold_listing_lock(label_zh: str, *, wait: bool = True) -> AsyncIterator[None]:
    """持有全局出品锁执行出品自动化。

    :param label_zh: 占用者的中文说明（如「正在出品」「自动补挂中」），冲突提示用。
    :param wait: True=排队等待（自动补挂）；False=已占用立刻抛 ``ListingBusyError``（手动入口）。
    """
    global _holder
    if not wait and _lock.locked():
        cur = str((_holder or {}).get("label_zh") or "已有其他用户正在出品")
        raise ListingBusyError(cur)
    await _lock.acquire()
    _holder = {"label_zh": label_zh, "started_at": time.time()}
    try:
        yield
    finally:
        _holder = None
        _lock.release()
