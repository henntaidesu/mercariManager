# -*- coding: utf-8 -*-
"""
按 account_key 使用独立 user_data_dir 启动 Microsoft Edge（Playwright channel=msedge），
Cookie 与站点数据随目录持久化；不同账号对应不同子浏览器配置目录。

Playwright 异步驱动绑定到「当前线程 + 当前 event loop」：
- 煤炉浏览器任务在 uvicorn 主事件循环上 ``await`` 执行（见 ``run_meilu_serial_async``），同一账号串行、不同账号可并行。
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

    __slots__ = ("lock", "playwright", "playwright_loop", "contexts", "session_meta")

    def __init__(self) -> None:
        self.lock: Optional[asyncio.Lock] = None
        self.playwright: Any = None
        self.playwright_loop: Optional[asyncio.AbstractEventLoop] = None
        self.contexts: Dict[str, Any] = {}
        # account_key -> {"interactive": bool, "headless": bool}
        self.session_meta: Dict[str, Dict[str, bool]] = {}


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
        仅关掉 pages[1:] 仍会出现两个相同页面；因此需要收敛到单标签。

        注意：不能先关掉全部页面再 new_page。Chromium/Edge 在「0 个标签」状态下
        常会触发 Target.createTarget: Failed to open a new tab。应始终在仍有标签时
        先 new_page，再关闭此前所有页面（不复用旧 Page）。
        """
        pages_before = list(context.pages)
        page = await context.new_page()
        for p in pages_before:
            try:
                await p.close()
            except Exception:
                pass
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
    def _prune_dead_sessions(s: _DriveThreadState) -> None:
        for k in list(s.contexts.keys()):
            c = s.contexts.get(k)
            if c is not None and EdgeWebDriveManager._is_context_alive(c):
                continue
            s.contexts.pop(k, None)
            s.session_meta.pop(k, None)

    @staticmethod
    def _session_meta(s: _DriveThreadState, key: str) -> Dict[str, bool]:
        return s.session_meta.get(key, {})

    @staticmethod
    def _is_interactive_session(s: _DriveThreadState, key: str) -> bool:
        ctx = s.contexts.get(key)
        if ctx is None or not EdgeWebDriveManager._is_context_alive(ctx):
            return False
        return bool(s.session_meta.get(key, {}).get("interactive"))

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
            meta = self._session_meta(s, key)
            out.append(
                {
                    "account_key": key,
                    "profile_dir": os.path.join(profiles_root(), key),
                    "open_pages": pages,
                    "interactive": bool(meta.get("interactive")),
                    "headless": bool(meta.get("headless")),
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
        interactive: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        :param interactive: 用户手动打开的可见会话（不会被 MITM 自动化 ``close_session_if_automation`` 关闭）。
            默认：``headless=False`` 时为 True，``headless=True`` 时为 False。
        """
        key = validate_account_key(account_key)
        if interactive is None:
            interactive = not headless
        async with self._serialize_profile(key):
            return await self._open_session_impl(
                key,
                headless=headless,
                start_url=start_url,
                proxy_server=proxy_server,
                interactive=interactive,
            )

    def is_interactive_session_running(self, account_key: str) -> bool:
        """主 profile（``meilu_{id}``）上是否有用户手动打开的有头会话。"""
        key = validate_account_key(account_key)
        s = self._ts()
        self._prune_dead_sessions(s)
        return self._is_interactive_session(s, key)

    async def copy_cookies_between_sessions(self, src_key: str, dst_key: str) -> int:
        """
        从源会话（通常为有头 ``meilu_{id}``）复制 Cookie 到目标会话（``meilu_{id}__auto``）。
        主 profile 的 Cookies 文件被有头 Edge 占用时无法落盘复制，但运行中会话可读 Cookie。
        """
        src = validate_account_key(src_key)
        dst = validate_account_key(dst_key)
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            src_ctx = s.contexts.get(src)
            dst_ctx = s.contexts.get(dst)
            if (
                src_ctx is None
                or dst_ctx is None
                or not self._is_context_alive(src_ctx)
                or not self._is_context_alive(dst_ctx)
            ):
                return 0
            try:
                cookies = await src_ctx.cookies()
            except Exception:
                return 0
            if not cookies:
                return 0
            if not dst_ctx.pages:
                await dst_ctx.new_page()
            try:
                await dst_ctx.add_cookies(cookies)
                return len(cookies)
            except Exception:
                return 0

    async def reload_active_tab(
        self,
        account_key: str,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 60000,
    ) -> None:
        """刷新目标会话当前标签页（MITM 等待超时前重试拉取 API）。"""
        key = validate_account_key(account_key)
        u = (url or "").strip()
        if not u:
            return
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            ctx = s.contexts.get(key)
            if ctx is None or not self._is_context_alive(ctx):
                return
            page = ctx.pages[-1] if ctx.pages else await ctx.new_page()
            await page.goto(u, wait_until=wait_until, timeout=timeout_ms)

    async def ensure_session_for_mitm(
        self,
        account_key: str,
        *,
        start_url: Optional[str],
        proxy_server: Optional[str],
        headless: bool,
    ) -> Dict[str, Any]:
        """
        MITM 用：在 ``meilu_{id}__auto`` 独立 profile 上启动新的无头（或指定 headless）会话。
        不触碰 ``meilu_{id}`` 上有头用户窗口。
        """
        key = validate_account_key(account_key)
        async with self._serialize_profile(key):
            await self._close_session_unlocked(key, force=True)
            return await self._open_session_impl(
                key,
                headless=headless,
                start_url=start_url,
                proxy_server=proxy_server,
                interactive=False,
            )

    async def close_session_if_automation(self, account_key: str) -> Dict[str, Any]:
        """关闭 ``__auto`` 自动化会话；主 profile 有头会话请用 ``close_session``。"""
        return await self.close_session(account_key, force=True)

    async def _open_session_impl(
        self,
        key: str,
        *,
        headless: bool = False,
        start_url: Optional[str] = None,
        proxy_server: Optional[str] = None,
        interactive: bool = False,
    ) -> Dict[str, Any]:
        s = self._prepare_async()
        async with s.lock:  # type: ignore[union-attr]
            self._prune_dead_sessions(s)

            ctx = s.contexts.get(key)
            meta = self._session_meta(s, key)

            if ctx is not None and self._is_context_alive(ctx):
                if interactive and not meta.get("interactive"):
                    try:
                        await ctx.close()
                    except Exception:
                        pass
                    s.contexts.pop(key, None)
                    s.session_meta.pop(key, None)
                    ctx = None
            ctx = s.contexts.get(key)
            if ctx is not None and self._is_context_alive(ctx):
                if start_url:
                    try:
                        await self._navigate_one_tab(ctx, start_url)
                    except Exception:
                        s.contexts.pop(key, None)
                        s.session_meta.pop(key, None)
                        ctx = None
                else:
                    out = {
                        "account_key": key,
                        "already_running": True,
                        "profile_dir": profile_dir_for(key),
                        "profiles_root": profiles_root(),
                        "interactive": bool(meta.get("interactive")),
                    }
                    return out

            if ctx is not None and self._is_context_alive(ctx):
                out = {
                    "account_key": key,
                    "already_running": True,
                    "profile_dir": profile_dir_for(key),
                    "profiles_root": profiles_root(),
                    "interactive": bool(meta.get("interactive")),
                }
                return out

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
            s.session_meta[key] = {"interactive": bool(interactive), "headless": bool(headless)}
            if start_url:
                await self._navigate_one_tab(context, start_url)

            return {
                "account_key": key,
                "already_running": False,
                "profile_dir": udir,
                "profiles_root": profiles_root(),
                "proxy_server": ps or None,
                "interactive": bool(interactive),
            }

    async def _close_session_unlocked(
        self,
        key: str,
        *,
        only_automation: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        s = self._prepare_async()
        closed = False
        async with s.lock:  # type: ignore[union-attr]
            self._prune_dead_sessions(s)
            meta = self._session_meta(s, key)
            if only_automation and not force and meta.get("interactive"):
                return {
                    "account_key": key,
                    "closed": False,
                    "skipped": "interactive",
                }
            ctx = s.contexts.pop(key, None)
            s.session_meta.pop(key, None)
            if ctx is None:
                return {"account_key": key, "closed": False}
            try:
                if self._is_context_alive(ctx):
                    await ctx.close()
                    closed = True
            except Exception:
                pass
        if closed:
            await asyncio.sleep(self._profile_release_delay_sec())
        return {"account_key": key, "closed": closed}

    async def close_session(
        self,
        account_key: str,
        *,
        only_automation: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        key = validate_account_key(account_key)
        async with self._serialize_profile(key):
            return await self._close_session_unlocked(
                key, only_automation=only_automation, force=force
            )

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
            s.session_meta.clear()
            if s.playwright is not None:
                try:
                    await s.playwright.stop()
                except Exception:
                    pass
                s.playwright = None
                s.playwright_loop = None
            s.lock = None
