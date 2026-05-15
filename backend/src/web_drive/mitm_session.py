# -*- coding: utf-8 -*-
"""
MITM 自动化：在独立 profile（``meilu_{id}__auto``）上启动新的无头 Edge，
不复用、不关闭账号页手动打开的有头浏览器（``meilu_{id}``）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Tuple

from ..ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy
from .manager import EdgeWebDriveManager, get_web_drive_manager
from .paths import meilu_automation_key, seed_automation_profile_from_account


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
    auto_key = meilu_automation_key(account_id)
    seed_automation_profile_from_account(account_id)
    await mgr.ensure_session_for_mitm(
        auto_key,
        start_url=start_url,
        proxy_server=default_mitm_proxy_url(),
        headless=headless,
    )
    try:
        yield mgr, auto_key
    finally:
        await mgr.close_session(auto_key, force=True)
