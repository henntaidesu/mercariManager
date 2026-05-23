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
    if os.environ.get("SSL_MITM_AUTO_START", "1").strip().lower() not in ("0", "false", "no", "off"):
        from src.ssl_mitm_proxy.runner import start_mitm_proxy

        r = start_mitm_proxy()
        if r.get("error"):
            logging.getLogger(__name__).warning("SSL MITM 未启动: %s", r["error"])

    from src.meilu_auto_fetch_loop import meilu_auto_fetch_loop

    asyncio.create_task(meilu_auto_fetch_loop())

    async def _startup_web_drive_browsers() -> None:
        # 煤炉账号页「打开浏览器」：有头 meilu_{id}；INTERACTIVE_BROWSER_AUTO_START=0 可关闭
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
    from src.ssl_mitm_proxy.runner import stop_mitm_proxy

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
