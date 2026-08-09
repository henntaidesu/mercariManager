# -*- coding: utf-8 -*-
"""雅虎 App 授权登录的浏览器侧：开一个独立会话，等回跳到自定义 scheme 后把 code 交出去。

**为什么要开浏览器**：雅虎没有账密登录接口，App 自己也是把 ``login.yahoo.co.jp`` 的登录页
塞进 WebView 让用户手输（含二次验证 / passkey）。这里做的是同一件事，只是把 WebView 换成
Edge——授权端点、client_id、redirect_uri、PKCE 全部照抄 App，换回来的是真的 App 令牌。

**profile 是独立的**（``mercari_{id}__appauth``），不与网页自动化共用 Cookie 罐：这是
「App 令牌不与网页混用」的落点。也因此每次调用默认 ``fresh=True`` 清空重来——上一次登录残留
的会话会让雅虎直接跳过登录页，用户就没机会换账号了。

回跳地址 ``yj-paypay-fleamarket:/?code=…`` 是 Chromium 不认识的 scheme。实测三个事件都能拿到
它（``response`` 的 Location 头、``request``、``requestfailed``），这里三个都挂上：
任何一个先到都算数，避免依赖单一信号在不同 Edge 版本上的差异。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .core.manager import get_web_drive_manager
from .core.paths import mercari_app_auth_key

log = logging.getLogger(__name__)

#: App 的自定义回跳 scheme（``YJLoginManager`` 里写死的 customUriScheme）
REDIRECT_SCHEME = "yj-paypay-fleamarket:"


def _parse_redirect(url: str) -> Dict[str, str]:
    """``yj-paypay-fleamarket:/#code=…&state=…`` → dict。

    **参数在 fragment 里，不是 query**：``response_type=code id_token`` 是 OIDC 混合流，
    按规范响应一律用 fragment 编码。query 那一份也照收，一来纯 ``code`` 流是 query，
    二来雅虎哪天改了不至于全盘失效。

    自定义 scheme 在 ``urlparse`` 眼里是 opaque 的，query 有时会连在 ``path`` 上，所以
    ``path`` 里的 ``?`` 也扫一遍。
    """
    parsed = urlparse(url)
    chunks = [parsed.fragment or "", parsed.query or ""]
    if "?" in (parsed.path or ""):
        chunks.append(parsed.path.split("?", 1)[1])
    out: Dict[str, str] = {}
    for raw in chunks:
        for key, vals in parse_qs(raw, keep_blank_values=True).items():
            out.setdefault(key, vals[0] if vals else "")
    return out


async def capture_authorization_code(
    account_id: int,
    *,
    authorize_url: str,
    timeout_sec: int = 300,
    headless: bool = False,
) -> Dict[str, str]:
    """打开登录窗口并等待授权回跳，返回回跳 URL 上的查询参数（含 ``code`` / ``state``）。

    ``headless=True`` 只在「雅虎侧已有会话、无需交互」时才可能成功，正常登录必须有头。
    """
    key = mercari_app_auth_key(int(account_id))
    mgr = get_web_drive_manager()
    captured: Dict[str, str] = {}
    seen_bare = False
    done = asyncio.Event()

    def _on_url(url: str) -> None:
        """收到一个疑似回跳地址；**只有带参数的那一份算数**。

        同一次回跳会从三个事件各来一遍，而 ``request`` / ``requestfailed`` 上的 URL 被
        Chromium 剥掉了 fragment（实测只剩 ``yj-paypay-fleamarket:/``）——它们通常还先到。
        谁先到就收谁的话，拿到的就是个空壳，code/state 全丢。
        """
        nonlocal seen_bare
        if not url or not url.startswith(REDIRECT_SCHEME) or done.is_set():
            return
        params = _parse_redirect(url)
        if not (params.get("code") or params.get("error")):
            seen_bare = True
            return
        captured.update(params)
        done.set()

    # fresh=True：清掉上一次的登录态，否则雅虎会直接跳过登录页复用上次的账号
    await mgr.open_session(
        key,
        headless=bool(headless),
        interactive=not headless,
        restore_tabs=False,
        fresh=True,
        start_url="about:blank",
    )
    page = await mgr.active_tab_page(key)

    page.on("request", lambda r: _on_url(r.url))
    page.on("requestfailed", lambda r: _on_url(r.url))
    page.on(
        "response",
        lambda r: _on_url((r.headers or {}).get("location", "")),
    )

    try:
        # 回跳到未知 scheme 时 goto 本身会抛（导航失败），这不是错误——事件里已经拿到 code
        await page.goto(authorize_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as exc:  # noqa: BLE001
        log.debug("[yahoo_app_login] 首次导航结束于异常（通常是回跳到自定义 scheme）：%s", exc)

    try:
        await asyncio.wait_for(done.wait(), timeout=float(timeout_sec))
    except asyncio.TimeoutError:
        if seen_bare:
            # 回跳确实发生了，但三个事件给的 URL 上都没有参数——那就不是「用户没登录完」，
            # 而是这条链路本身出了问题，得说清楚，别让人反复重登。
            raise TimeoutError(
                "已回跳到 App 的 redirect_uri，但地址上没有 code/state（fragment 可能被拦掉了）。"
                "这不是登录没走完，请把这条信息反馈给开发者。"
            )
        raise TimeoutError(
            f"等待雅虎授权回跳超时（{timeout_sec}s）。请在打开的浏览器窗口里完成登录与授权；"
            "若窗口已停在登录页，说明这次登录没有走完。"
        )
    finally:
        # 登录窗口留着没意义，且里面是登录态——用完即关
        try:
            await mgr.close_session(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("[yahoo_app_login] 关闭登录会话失败 key=%s：%s", key, exc)

    if captured.get("error"):
        raise RuntimeError(
            f"雅虎拒绝了这次授权：{captured.get('error')} "
            f"{captured.get('error_description') or ''}".strip()
        )
    return captured
