import logging
import os
import sys
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.db_manage.db_manager import init_database
from src.use_web.image_storage import ensure_image_dir
from src.API import router as v2_router
from src.app_paths import backend_root

# ─────────────────────────────────────────────────────────────────────────
# 全局调试开关：强制所有自动化浏览器「有头」
#   False（默认）= 走正常无头逻辑（受 WEB_DRIVE_AUTOMATION_HEADLESS 环境变量控制，默认无头）
#   True          = 无视环境变量与各处 headless=True 入参，所有自动化浏览器一律有头，方便肉眼 DEBUG
# 改这一处即可全局生效（启动时通过 set_force_headed_debug 应用）。
# 注：环境变量 WEB_DRIVE_FORCE_HEADED_DEBUG=1 也可临时开启，便于不改码调试。
WEB_DRIVE_FORCE_HEADED_DEBUG = False


def _resolve_force_headed_debug() -> bool:
    env = os.environ.get("WEB_DRIVE_FORCE_HEADED_DEBUG")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return WEB_DRIVE_FORCE_HEADED_DEBUG


app = FastAPI(title="mercari V2 订单管理", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/imges", StaticFiles(directory=ensure_image_dir()), name="imges")

# 注册 V2 根路由 → /mercariV2/src/...
app.include_router(v2_router, prefix="/mercariV2")


@app.on_event("startup")
async def startup():
    # 保证业务代码里 logging.info 能出现在 Uvicorn 同一控制台（默认根 logger 常为 WARNING）
    _fmt = "%(levelname)s | %(name)s | %(message)s"
    try:
        logging.basicConfig(level=logging.INFO, format=_fmt, force=True)
    except TypeError:
        logging.basicConfig(level=logging.INFO, format=_fmt)
    init_database()

    # 应用「强制有头调试」全局开关（在任何浏览器启动前设定）
    from src.web_drive.core.manager import set_force_headed_debug

    _force_headed = _resolve_force_headed_debug()
    set_force_headed_debug(_force_headed)
    if _force_headed:
        logging.getLogger(__name__).warning(
            "[web_drive] 强制有头调试已开启：所有自动化浏览器将以有头方式启动"
        )

    if os.environ.get("SSL_MITM_AUTO_START", "1").strip().lower() not in ("0", "false", "no", "off"):
        from src.ssl_mitm_proxy.runner import start_mitm_proxy

        r = start_mitm_proxy()
        if r.get("error"):
            logging.getLogger(__name__).warning("SSL MITM 未启动: %s", r["error"])

    from src.mercari_auto_fetch_loop import mercari_auto_fetch_loop

    asyncio.create_task(mercari_auto_fetch_loop())

    async def _startup_web_drive_browsers() -> None:
        # 煤炉账号页「打开浏览器」：有头 mercari_{id}；INTERACTIVE_BROWSER_AUTO_START=0 可关闭
        from src.web_drive.core.interactive_browser import (
            startup_interactive_browsers_for_all_active_accounts,
        )

        await startup_interactive_browsers_for_all_active_accounts()

    if os.environ.get("INTERACTIVE_BROWSER_AUTO_START", "0").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        asyncio.create_task(_startup_web_drive_browsers())


@app.on_event("shutdown")
async def shutdown_web_drive():
    from src.web_drive import get_web_drive_manager, shutdown_serial_executors
    from src.web_drive.core.account_serial_queue import shutdown_queue
    from src.ssl_mitm_proxy.runner import stop_mitm_proxy

    await shutdown_queue()
    shutdown_serial_executors(wait=False)
    await get_web_drive_manager().shutdown()
    stop_mitm_proxy()


@app.get("/api/health")
def health():
    """兼容旧的健康检查路径（部分调用方仍使用 /api/health）。V2 路径为 /mercariV2/health。"""
    return {"status": "ok", "message": "mercari 订单管理运行中"}


def _webside_dist_dir() -> Path:
    override = (os.environ.get("MERCARI_WEBSIDE_DIST") or "").strip()
    if override:
        return Path(override)
    root = backend_root()
    if getattr(sys, "frozen", False):
        return root / "webside" / "dist"
    # 开发目录：仓库内 webside 与 backend 同级
    return root.parent / "webside" / "dist"


_spa_dir = _webside_dist_dir()
if (
    _spa_dir.is_dir()
    and os.environ.get("MERCARI_NO_STATIC", "").strip().lower()
    not in ("1", "true", "yes", "on")
):
    app.mount(
        "/",
        StaticFiles(directory=str(_spa_dir), html=True),
        name="spa",
    )


# ─────────────────────────────────────────────────────────────────────────
# 直接运行（不经 nginx）时的 TLS 证书解析
#   - 经 nginx 反代：后端跑普通 HTTP，由 nginx 终止 TLS（无需下列任何变量）。
#   - 直连端口 / 内网想要 HTTPS：设置下列任一组，让后端自己加载证书提供 https。
# 优先级：
#   1) 显式文件：MERCARI_SSL_CERTFILE + MERCARI_SSL_KEYFILE
#   2) 证书文件夹：MERCARI_SSL_CERT_DIR（自动在其中查找常见命名，含 Let's Encrypt
#      的 fullchain.pem / privkey.pem）
#   3) 都未配置 → 普通 HTTP 启动
# ─────────────────────────────────────────────────────────────────────────
def _resolve_ssl_config() -> tuple[str | None, str | None]:
    certfile = (os.environ.get("MERCARI_SSL_CERTFILE") or "").strip()
    keyfile = (os.environ.get("MERCARI_SSL_KEYFILE") or "").strip()
    if certfile and keyfile:
        return certfile, keyfile

    cert_dir = (os.environ.get("MERCARI_SSL_CERT_DIR") or "").strip()
    if cert_dir:
        d = Path(cert_dir)
        # 证书（含中间链优先）与私钥的常见文件名
        cert_candidates = [
            "fullchain.pem", "fullchain.cer", "cert.pem",
            "certificate.crt", "server.crt", "server.pem",
        ]
        key_candidates = ["privkey.pem", "private.key", "key.pem", "server.key"]
        found_cert = next((str(d / n) for n in cert_candidates if (d / n).is_file()), None)
        found_key = next((str(d / n) for n in key_candidates if (d / n).is_file()), None)
        if found_cert and found_key:
            return found_cert, found_key
        logging.getLogger(__name__).warning(
            "MERCARI_SSL_CERT_DIR=%s 中未找到匹配的证书/私钥（cert=%s, key=%s），将以 HTTP 启动",
            cert_dir, found_cert, found_key,
        )
    return None, None


if __name__ == "__main__":
    import uvicorn

    host = (os.environ.get("MERCARI_HOST") or "0.0.0.0").strip()
    port = int((os.environ.get("MERCARI_PORT") or "9601").strip())
    forwarded_allow_ips = (os.environ.get("MERCARI_FORWARDED_ALLOW_IPS") or "127.0.0.1").strip()
    certfile, keyfile = _resolve_ssl_config()
    key_password = (os.environ.get("MERCARI_SSL_KEY_PASSWORD") or "").strip() or None

    ssl_kwargs: dict = {}
    if certfile and keyfile:
        ssl_kwargs["ssl_certfile"] = certfile
        ssl_kwargs["ssl_keyfile"] = keyfile
        if key_password:
            ssl_kwargs["ssl_keyfile_password"] = key_password
        print(f"[mercari] HTTPS 直连启动：https://{host}:{port}  (cert={certfile})")
    else:
        print(
            f"[mercari] HTTP 启动：http://{host}:{port}  "
            "(如需后端直连 HTTPS，设置 MERCARI_SSL_CERT_DIR 或 MERCARI_SSL_CERTFILE/MERCARI_SSL_KEYFILE)"
        )

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
        **ssl_kwargs,
    )
