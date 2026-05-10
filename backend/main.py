import logging
import os

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from src.auth import require_auth
from src.db_manage.db_manager import init_database
from src.image_storage import ensure_image_dir
from src.routes.categories import router as categories_router
from src.routes.warehouses import router as warehouses_router
from src.routes.product_types import router as product_types_router
from src.routes.inventory import router as inventory_router
from src.routes.products import public_router as inventory_public_router
from src.routes.transactions import router as transactions_router
from src.routes.scan import router as scan_router
from src.routes.auth import router as auth_router
from src.routes.ocr import router as ocr_router
from src.routes.cost_records import router as cost_records_router
from src.routes.cost_expenses import router as cost_expenses_router
from src.routes.orders import router as orders_router
from src.routes.meilu_accounts import router as meilu_accounts_router
from src.routes.on_sale_items import router as on_sale_items_router
from src.routes.product_type_category_mappings import router as product_type_category_mappings_router
from src.routes.web_drive import router as web_drive_router
from src.routes.ssl_mitm import router as ssl_mitm_router
from src.operation_mercari.API import router as mercari_router

app = FastAPI(title="mercari 订单管理", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/imges", StaticFiles(directory=ensure_image_dir()), name="imges")

auth_required = [Depends(require_auth)]

app.include_router(inventory_public_router)  # 缩略图等公开接口，无需登录
app.include_router(categories_router, dependencies=auth_required)
app.include_router(warehouses_router, dependencies=auth_required)
app.include_router(product_types_router, dependencies=auth_required)
app.include_router(inventory_router, dependencies=auth_required)
app.include_router(transactions_router, dependencies=auth_required)
app.include_router(scan_router, dependencies=auth_required)
app.include_router(ocr_router, dependencies=auth_required)
app.include_router(cost_records_router, dependencies=auth_required)
app.include_router(cost_expenses_router, dependencies=auth_required)
app.include_router(orders_router, dependencies=auth_required)
app.include_router(meilu_accounts_router, dependencies=auth_required)
app.include_router(mercari_router, dependencies=auth_required)
app.include_router(on_sale_items_router, dependencies=auth_required)
app.include_router(product_type_category_mappings_router, dependencies=auth_required)
app.include_router(web_drive_router, dependencies=auth_required)
app.include_router(ssl_mitm_router, dependencies=auth_required)
app.include_router(auth_router)


@app.on_event("startup")
def startup():
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


@app.on_event("shutdown")
async def shutdown_web_drive():
    from src.web_drive import get_web_drive_manager, shutdown_serial_executors
    from src.ssl_mitm_proxy.runner import stop_mitm_proxy

    shutdown_serial_executors(wait=False)
    await get_web_drive_manager().shutdown()
    stop_mitm_proxy()


@app.get("/api/health")
def health():
    return {"status": "ok", "message": "mercari 订单管理运行中"}
