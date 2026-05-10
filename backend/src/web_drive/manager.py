# -*- coding: utf-8 -*-
"""
按 account_key 使用独立 user_data_dir 启动 Microsoft Edge（Playwright channel=msedge），
Cookie 与站点数据随目录持久化；不同账号对应不同子浏览器配置目录。

Playwright 异步驱动绑定到「当前线程 + 当前 event loop」：
- FastAPI 的 async 路由跑在 uvicorn 主事件循环；sync 路由在线程池里 ``asyncio.run()``，每次都会新建并关闭 loop。
- 若在线程间共享同一个 Playwright 实例，或复用已随 loop 关闭而失效的实例，会触发
  ``'NoneType' object has no attribute 'send'``。
因此每个 **操作系统线程** 使用独立的 Playwright / contexts（``threading.local()``）。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from .paths import profile_dir_for, profiles_root, validate_account_key

_manager: Optional["EdgeWebDriveManager"] = None


def get_web_drive_manager() -> "EdgeWebDriveManager":
    global _manager
    if _manager is None:
        _manager = EdgeWebDriveManager()
    return _manager


class _DriveThreadState:
    """单个 OS 线程内的浏览器状态（Lock / Playwright / 会话表）。"""

    __slots__ = ("lock", "playwright", "playwright_loop", "contexts")

    def __init__(self) -> None:
        self.lock: Optional[asyncio.Lock] = None
        self.playwright: Any = None
        self.playwright_loop: Optional[asyncio.AbstractEventLoop] = None
        self.contexts: Dict[str, Any] = {}


class EdgeWebDriveManager:
    """管理多账号 Edge 持久化会话（每账号独立 profile 目录）。"""

    # 同一 profile 目录只能被一个线程「关→开」；否则 Windows 下易出现 SingletonLock / 句柄未释放，
    # Edge 瞬间退出（exitCode≈21）并报 Target ... has been closed。
    _profile_outer_locks: Dict[str, threading.Lock] = {}
    _profile_outer_locks_guard = threading.Lock()

    def __init__(self) -> None:
        self._tls = threading.local()

    @classmethod
    def _outer_lock_for_profile(cls, account_key: str) -> threading.Lock:
        with cls._profile_outer_locks_guard:
            if account_key not in cls._profile_outer_locks:
                cls._profile_outer_locks[account_key] = threading.Lock()
            return cls._profile_outer_locks[account_key]

    @staticmethod
    def _profile_release_delay_sec() -> float:
        try:
            return float((os.environ.get("WEB_DRIVE_PROFILE_RELEASE_DELAY_SEC") or "0.45").strip())
        except ValueError:
            return 0.45

    @staticmethod
    def _launch_retry_delays_sec() -> List[float]:
        raw = (os.environ.get("WEB_DRIVE_LAUNCH_RETRY_DELAYS_SEC") or "0,0.7,1.4").strip()
        out: List[float] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(float(part))
            except ValueError:
                pass
        return out if out else [0.0, 0.7, 1.4]

    @asynccontextmanager
    async def _serialize_profile(self, account_key: str):
        lock = self._outer_lock_for_profile(account_key)
        await asyncio.to_thread(lock.acquire)
        try:
            yield
        finally:
            lock.release()

    def _ts(self) -> _DriveThreadState:
        s = getattr(self._tls, "state", None)
        if s is None:
            s = _DriveThreadState()
            self._tls.state = s
        return s

    def _prepare_async(self) -> _DriveThreadState:
        """在 async 方法开头调用：确保本线程有 asyncio.Lock（绑定当前运行中的 loop）。"""
        s = self._ts()
        if s.lock is None:
            s.lock = asyncio.Lock()
        return s

    @staticmethod
    async def _navigate_one_tab(
        context: Any,
        start_url: str,
        *,
        wait_until: str = "domcontentloaded",
    ) -> None:
        """只保留一个标签并打开 start_url。

        Edge 持久化 profile 的「继续浏览上次页面」可能在 launch 后异步再开标签，
        仅关掉 pages[1:] 仍会出现两个相同页面；因此先关掉启动时所有页再 new_page，
        并在 goto 后短循环关闭晚到的恢复标签。
        """
        for p in list(context.pages):
            try:
                await p.close()
            except Exception:
                pass
        page = await context.new_page()
        await page.goto(start_url, wait_until=wait_until)
        for _ in range(12):
            extra = [p for p in context.pages if p is not page]
            if not extra:
                break
            for p in extra:
                try:
                    await p.close()
                except Exception:
                    pass
            await asyncio.sleep(0.15)

    @staticmethod
    def _drop_stale_playwright(s: _DriveThreadState, running: asyncio.AbstractEventLoop) -> None:
        """本线程内：当前 loop 与创建 Playwright 时不一致则丢弃缓存（常见于连续多次 asyncio.run）。"""
        if s.playwright is None:
            s.playwright_loop = None
            return
        if s.playwright_loop is running:
            return
        s.playwright = None
        s.playwright_loop = None

    async def _ensure_playwright(self, s: _DriveThreadState) -> Any:
        running = asyncio.get_running_loop()
        self._drop_stale_playwright(s, running)

        if s.playwright is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 playwright，请在 backend 目录执行: pip install playwright && playwright install msedge"
                ) from exc
            s.playwright = await async_playwright().start()
            s.playwright_loop = running

        return s.playwright

    @staticmethod
    def _purge_non_auth_cache(user_data_dir: str) -> None:
        """清理浏览器运行期缓存，尽量保留登录态相关数据（cookies/local storage/indexeddb）。"""
        if not user_data_dir or not os.path.isdir(user_data_dir):
            return

        targets = [
            os.path.join(user_data_dir, "Default", "Cache"),
            os.path.join(user_data_dir, "Default", "Code Cache"),
            os.path.join(user_data_dir, "Default", "GPUCache"),
            os.path.join(user_data_dir, "Default", "DawnCache"),
            os.path.join(user_data_dir, "Default", "DawnGraphiteCache"),
            os.path.join(user_data_dir, "Default", "DawnWebGPUCache"),
            os.path.join(user_data_dir, "Default", "Service Worker", "CacheStorage"),
            os.path.join(user_data_dir, "Default", "Media Cache"),
            os.path.join(user_data_dir, "GrShaderCache"),
            os.path.join(user_data_dir, "ShaderCache"),
        ]
        for p in targets:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                # 清理失败不影响浏览器启动
                pass

        # 这类文件不影响登录态，但可减少站点缓存/状态噪音
        files = [
            os.path.join(user_data_dir, "Default", "Network Action Predictor"),
            os.path.join(user_data_dir, "Default", "Network Action Predictor-journal"),
        ]
        for f in files:
            try:
                if os.path.isfile(f):
                    os.remove(f)
            except Exception:
                pass

    @staticmethod
    def _is_context_alive(ctx: Any) -> bool:
        """用户手动关窗后 Playwright 上下文已关闭，但字典里可能仍留着引用。"""
        if ctx is None:
            return False
        try:
            _ = list(ctx.pages)
            return True
        except Exception:
            return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出当前线程内仍存活的上下文（async 路由=主循环；sync+asyncio.run=线程池线程）。"""
        s = self._ts()
        out: List[Dict[str, Any]] = []
        for key, ctx in list(s.contexts.items()):
            if not self._is_context_alive(ctx):
                continue
            try:
                pages = len(ctx.pages)
            except Exception:
                continue
            out.append(
                {
                    "account_key": key,
                    "profile_dir": os.path.join(profiles_root(), key),
                    "open_pages": pages,
                }
            )
        return out

    async def open_session(
        self,
        account_key: str,
        *,
        headless: bool = False,
        start_url: Optional[str] = None,
        proxy_server: Optional[str] = None,
    ) -> Dict[str, Any]:
        key = validate_account_key(account_key)
        async with self._serialize_profile(key):
            return await self._open_session_impl(
                key,
                headless=headless,
                start_url=start_url,
                proxy_server=proxy_server,
            )

    async def _open_session_impl(
        self,
        key: str,
        *,
        headless: bool = False,
        start_url: Optional[str] = None,
        proxy_server: Optional[str] = None,
    ) -> Dict[str, Any]:
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            for k in list(s.contexts.keys()):
                c = s.contexts.get(k)
                if c is not None and not self._is_context_alive(c):
                    s.contexts.pop(k, None)

            ctx = s.contexts.get(key)

            if ctx is not None:
                if start_url:
                    try:
                        await self._navigate_one_tab(ctx, start_url)
                    except Exception:
                        s.contexts.pop(key, None)
                        ctx = None
                else:
                    return {
                        "account_key": key,
                        "already_running": True,
                        "profile_dir": profile_dir_for(key),
                        "profiles_root": profiles_root(),
                    }

            if ctx is not None:
                return {
                    "account_key": key,
                    "already_running": True,
                    "profile_dir": profile_dir_for(key),
                    "profiles_root": profiles_root(),
                }

            pw = await self._ensure_playwright(s)
            udir = profile_dir_for(key)
            launch_kw: Dict[str, Any] = {
                "user_data_dir": udir,
                "channel": "msedge",
                "headless": headless,
                "viewport": {"width": 1280, "height": 800},
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    # 减轻启动时再拉起「上次会话」标签（配合 _navigate_one_tab 收敛）
                    "--disable-session-crashed-bubble",
                    "--disable-infobars",
                ],
            }
            ps = (proxy_server or "").strip()
            if ps:
                launch_kw["proxy"] = {"server": ps}
                # 本地 mitmproxy 动态签发站点证书，未将 mitm CA 导入系统前 Edge 会报 ERR_CERT_AUTHORITY_INVALID
                launch_kw["ignore_https_errors"] = True

            delays = self._launch_retry_delays_sec()
            last_exc: Optional[BaseException] = None
            context = None
            for attempt, delay_sec in enumerate(delays):
                if delay_sec > 0:
                    await asyncio.sleep(delay_sec)
                try:
                    if attempt == 0:
                        self._purge_non_auth_cache(udir)
                    context = await pw.chromium.launch_persistent_context(**launch_kw)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
            if context is None:
                raise RuntimeError(
                    f"启动 Edge 失败（请确认已安装 Microsoft Edge，并已执行 playwright install msedge；"
                    f"或关闭其它占用该账号 profile 的 Edge 窗口后重试；已重试 {len(delays)} 次）: {last_exc}"
                ) from last_exc

            s.contexts[key] = context
            if start_url:
                await self._navigate_one_tab(context, start_url)

            return {
                "account_key": key,
                "already_running": False,
                "profile_dir": udir,
                "profiles_root": profiles_root(),
                "proxy_server": ps or None,
            }

    async def close_session(self, account_key: str) -> Dict[str, Any]:
        key = validate_account_key(account_key)
        async with self._serialize_profile(key):
            s = self._prepare_async()
            async with s.lock:  # type: ignore[union-attr]
                ctx = s.contexts.pop(key, None)
                if ctx is None:
                    return {"account_key": key, "closed": False}
                try:
                    if self._is_context_alive(ctx):
                        await ctx.close()
                except Exception:
                    pass
            # 释放 user_data_dir 文件锁，避免紧接着 launch_persistent_context 时 Edge 秒退
            await asyncio.sleep(self._profile_release_delay_sec())
            return {"account_key": key, "closed": True}

    async def click_xpath(
        self,
        account_key: str,
        xpath: str,
        *,
        timeout_ms: int = 20000,
    ) -> Dict[str, Any]:
        key = validate_account_key(account_key)
        xp = (xpath or "").strip()
        if not xp:
            raise ValueError("xpath 不能为空")
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            ctx = s.contexts.get(key)
            if ctx is None or not self._is_context_alive(ctx):
                raise RuntimeError(f"会话未运行: {key}")
            # 始终操作最后打开的标签页：
            # Step2 click → pages[-1]=取引中(open_new_tab后) → 点进交易详情
            # Step4 click → pages[-1]=出品一覧(open_new_tab后) → 点进商品详情
            page = ctx.pages[-1] if ctx.pages else await ctx.new_page()
            locator = page.locator(f"xpath={xp}")
            await locator.first.wait_for(state="visible", timeout=timeout_ms)
            await locator.first.click(timeout=timeout_ms)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
            return {"account_key": key, "clicked": True, "xpath": xp}

    async def open_new_tab(
        self,
        account_key: str,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 30000,
    ) -> Dict[str, Any]:
        key = validate_account_key(account_key)
        u = (url or "").strip()
        if not u:
            raise ValueError("url 不能为空")
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            ctx = s.contexts.get(key)
            if ctx is None or not self._is_context_alive(ctx):
                raise RuntimeError(f"会话未运行: {key}")
            page = await ctx.new_page()
            await page.goto(u, wait_until=wait_until, timeout=timeout_ms)
            return {"account_key": key, "opened": True, "url": u}

    async def shutdown(self) -> None:
        """关闭当前线程内的所有会话与 Playwright（仅影响调用方所在线程）。"""
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            for key in list(s.contexts.keys()):
                ctx = s.contexts.pop(key, None)
                if ctx is not None:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
            if s.playwright is not None:
                try:
                    await s.playwright.stop()
                except Exception:
                    pass
                s.playwright = None
                s.playwright_loop = None
