# -*- coding: utf-8 -*-
"""
MITM 自动化：每次操作启动一个**独立的有头最小化** Edge 进程执行任务，
操作完成后整体关闭该浏览器进程。不再依赖持久化无头浏览器，也不再从有头主会话内存注入 Cookie。

每次任务的完整生命周期：
  1. 确保 MITM 代理已启动
  2. 把 ``meilu_{id}`` profile 磁盘上的 Cookie / 登录文件复制到 ``meilu_{id}__auto`` profile
  3. 以 ``headless=False, start_minimized=True`` 启动一个新的 ``__auto`` Edge 进程
     （加载 MITM 代理 + 自带最新磁盘 Cookie）
  4. 在该浏览器内打开 ``start_url``
  5. yield ``(mgr, auto_key)`` —— 与旧接口完全兼容
  6. 操作结束（或抛错）后 ``close_session(force=True)`` 整体关闭浏览器

设计动机：
  - 旧版（持久化无头 + 内存 Cookie 注入）要求 ``meilu_{id}`` 有头会话**正在运行**，
    否则 ``copy_cookies_between_sessions`` 拿不到源 Cookie，无头窗口里的会话很快失效；
  - 新版直接从磁盘 seed Cookie，用户只要在账号管理页登录过一次并**关闭该窗口**让
    Cookie 刷盘，后续任意 MITM 操作都能从磁盘自取登录态。

使用前置：
  - ``meilu_{id}`` 有头主窗口正在运行时，Windows 上其 Cookie/Login Data 文件被 Edge
    独占；seed 拷贝会跳过这些文件（``_seed_profile_auth_files`` 内部静默忽略），
    ``__auto`` 拿到的可能是上次刷盘的旧 Cookie。建议在 MITM 操作前先关闭该有头窗口。
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, Optional, Tuple

from ...ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy
from .manager import EdgeWebDriveManager, get_web_drive_manager
from .paths import (
    meilu_account_key,
    meilu_automation_key,
    seed_automation_profile_from_account,
)

log = logging.getLogger(__name__)

_MITM_PAGE_RELOAD_INTERVAL_SEC = 20.0


@asynccontextmanager
async def mitm_automation_browser(
    account_id: int,
    *,
    start_url: str,
) -> AsyncIterator[Tuple[EdgeWebDriveManager, str]]:
    """
    上下文管理器：为单次 MITM 操作启动一个独立的有头最小化 Edge 进程。

    **进入时：**
      1. 确保 MITM 代理已启动
      2. 从 ``meilu_{id}`` profile 磁盘 seed Cookie 到 ``meilu_{id}__auto``
      3. 启动有头最小化 ``__auto`` Edge 并打开 ``start_url``

    **退出时：**
      - 整体关闭 ``__auto`` 浏览器进程（不保留）

    yield ``(mgr, auto_key)`` 供调用方在该会话内执行后续操作。
    """
    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    mgr = get_web_drive_manager()
    main_key = meilu_account_key(account_id)
    auto_key = meilu_automation_key(account_id)

    # ── 提示：主有头窗口在跑会锁住部分 Cookie/Login 文件，seed 可能复制旧数据 ──
    if mgr.is_interactive_session_running(main_key):
        log.warning(
            "MITM seed 时检测到 %s 有头会话仍在运行，部分 Cookie 文件被 Edge 独占；"
            "如登录态较旧，请先关闭账号管理页的 Edge 窗口以刷盘 Cookie 后再重试。",
            main_key,
        )

    # ── 步骤1：每次都从 meilu_{id} profile 磁盘复制 Cookie 到 __auto profile ──
    try:
        seed_automation_profile_from_account(account_id)
    except Exception as exc:
        log.warning("MITM seed profile 失败 %s（仍尝试用上次磁盘 Cookie 启动）: %s", auto_key, exc)

    # ── 步骤2：启动独立的有头最小化 __auto Edge（自带最新磁盘 Cookie + MITM 代理）──
    proxy = default_mitm_proxy_url()
    await mgr.ensure_session_for_mitm(
        auto_key,
        start_url=start_url,
        proxy_server=proxy,
        headless=False,
        start_minimized=True,
    )

    s = mgr._prepare_async()
    async with s.lock:  # type: ignore[union-attr]
        ctx = s.contexts.get(auto_key)
        if ctx is None or not mgr._is_context_alive(ctx):
            raise RuntimeError(
                f"MITM 浏览器启动失败: {auto_key}。请检查 Edge / Playwright 状态后重试。"
            )

    try:
        yield mgr, auto_key
    finally:
        # ── 退出：整体关闭 __auto 浏览器（不再持久化）──
        try:
            await mgr.close_session(auto_key, force=True)
            log.debug(
                "MITM 浏览器已关闭 account_id=%d key=%s",
                account_id,
                auto_key,
            )
        except Exception as exc:
            log.warning("MITM 浏览器关闭失败 %s（忽略）: %s", auto_key, exc)


async def wait_mitm_capture(
    *,
    mgr: EdgeWebDriveManager,
    auto_key: str,
    start_url: str,
    read_response: Callable[[], Optional[Dict[str, Any]]],
    since_ms: int,
    wait_seconds: int,
    error_detail: str,
    reload_interval_sec: float = _MITM_PAGE_RELOAD_INTERVAL_SEC,
) -> Dict[str, Any]:
    """
    轮询 MITM 落盘文件；超时前按间隔刷新当前标签页以再次触发目标 API。

    ``mgr.reload_active_tab`` 始终操作 ``ctx.pages[-1]``；新版 ``mitm_automation_browser``
    每次都启动单标签浏览器，因此与旧持久化版本行为一致。
    """
    deadline = time.monotonic() + wait_seconds
    next_reload = time.monotonic() + reload_interval_sec
    while time.monotonic() < deadline:
        data = read_response()
        if data and int(data.get("ts") or 0) >= since_ms:
            return data
        if time.monotonic() >= next_reload:
            next_reload += reload_interval_sec
            try:
                await mgr.reload_active_tab(auto_key, start_url)
            except Exception as exc:
                log.debug("MITM 等待中刷新标签页失败: %s", exc)
        await asyncio.sleep(0.35)
    raise RuntimeError(
        f"{wait_seconds}s 内未截获目标 API 响应（{error_detail}）。"
        "请确认 MITM 已启动；并先在账号管理页对该账号完成 Mercari 登录后**关闭该窗口**，"
        "以便系统从磁盘 Cookie 启动独立的最小化 Edge 拉取数据。"
    )
