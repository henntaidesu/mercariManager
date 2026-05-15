# -*- coding: utf-8 -*-
"""
MITM 自动化：在独立 profile（``meilu_{id}__auto``）上启动新的无头 Edge，
不复用、不关闭账号页手动打开的有头浏览器（``meilu_{id}``）。

有头窗口已登录时：从运行中的 ``meilu_{id}`` 会话复制 Cookie 到 ``__auto``，
避免主 profile 的 Cookies 文件被占用导致 seed 失败。
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, Optional, Tuple

from ..ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy
from .manager import EdgeWebDriveManager, get_web_drive_manager
from .paths import meilu_account_key, meilu_automation_key, seed_automation_profile_from_account

log = logging.getLogger(__name__)

_MITM_PAGE_RELOAD_INTERVAL_SEC = 20.0


@asynccontextmanager
async def mitm_automation_browser(
    account_id: int,
    *,
    start_url: str,
    headless: bool,
) -> AsyncIterator[Tuple[EdgeWebDriveManager, str]]:
    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    mgr = get_web_drive_manager()
    main_key = meilu_account_key(account_id)
    auto_key = meilu_automation_key(account_id)
    seed_automation_profile_from_account(account_id)
    await mgr.ensure_session_for_mitm(
        auto_key,
        start_url=start_url,
        proxy_server=default_mitm_proxy_url(),
        headless=headless,
    )
    n_cookies = await mgr.copy_cookies_between_sessions(main_key, auto_key)
    if n_cookies > 0:
        log.info(
            "MITM 自动化已从有头会话 %s 注入 %s 条 Cookie 到 %s，重新打开目标页",
            main_key,
            n_cookies,
            auto_key,
        )
        await mgr.reload_active_tab(auto_key, start_url)
    try:
        yield mgr, auto_key
    finally:
        await mgr.close_session(auto_key, force=True)


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
    """轮询 MITM 落盘文件；超时前按间隔刷新页面以再次触发 API。"""
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
                log.debug("MITM 等待中刷新页面失败: %s", exc)
        await asyncio.sleep(0.35)
    raise RuntimeError(
        f"{wait_seconds}s 内未截获目标 API 响应（{error_detail}）。"
        "请确认 MITM 已启动；若仅在账号管理页有头浏览器中登录，请保持该窗口打开后重试"
        "（系统会从有头会话同步 Cookie 到无头 MITM 浏览器）。"
    )
