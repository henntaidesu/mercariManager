# 单文件打包后 backend.exe 自调用充当 mitmdump：带 MERCARI_RUN_MITMDUMP=1 启动时，
# 在加载任何业务模块前切换到 mitmdump 入口并退出（见 src/ssl_mitm_proxy/runner.py）。
import os as _os

if _os.environ.get("MERCARI_RUN_MITMDUMP") == "1":
    from src._mitmdump_entry import run_mitmdump

    run_mitmdump()

# 打包为 windowed（无 CMD 黑框）后默认没有 stdout/stderr：尽早分配一个隐藏的日志控制台，
# 让后续所有日志/print 有真实控制台可写（托盘可显示/隐藏该窗口）。仅 Windows 冻结态生效。
import sys as _sys

if getattr(_sys, "frozen", False) and _sys.platform == "win32":
    try:
        from src.console_win import setup_hidden_console

        setup_hidden_console()
    except Exception:  # noqa: BLE001
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.use_web.image_storage import ensure_image_dir
from src.API import router as v2_router
from src.lifecycle import register_lifecycle
from src.web_static import mount_spa, register_health

WEB_DRIVE_FORCE_HEADED_DEBUG = True
  # 强制启用 headed 模式以兼容部分环境（如 Windows 打包后）无法正常使用无头模式的情况  

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

# 生命周期事件、兼容健康检查、前端 SPA 静态托管
register_lifecycle(app, force_headed_debug=WEB_DRIVE_FORCE_HEADED_DEBUG)
register_health(app)
mount_spa(app)  # 须最后挂载：根路径 "/" 会兜底其余未匹配路由


if __name__ == "__main__":
    from src.server import run

    run(app)
