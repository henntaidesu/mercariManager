# -*- coding: utf-8 -*-
"""
use_web V2 API 聚合模块

层级蓝图注册：
- 从 src/API.py 接收前缀 /mercariV2/src
- 向下传递给各资源模块，添加 /use_web/<resource> 路径段
- 完整 URL 格式: /mercariV2/src/use_web/<resource>/<endpoint>
"""

from fastapi import APIRouter, Depends

from ..auth import require_auth

from .auth.API import router as auth_router
from .system.API import router as system_router
from .ssl_mitm.API import router as ssl_mitm_router
from .ocr.API import router as ocr_router
from .scan.API import router as scan_router
from .categories.API import router as categories_router
from .transactions.API import router as transactions_router
from .product_types.API import router as product_types_router
from .product_type_category_mappings.API import router as ptcm_router
from .app_config.API import router as app_config_router
from .cost_records.API import router as cost_records_router
from .cost_expenses.API import router as cost_expenses_router
from .warehouses.API import router as warehouses_router
from .web_drive.API import router as web_drive_router
from .on_sale_items.API import router as on_sale_items_router
from .orders.API import router as orders_router
from .inventory.API import router as inventory_router
from .inventory.API import public_router as inventory_public_router
from .meilu_accounts.API import router as meilu_accounts_router

router = APIRouter(prefix="/use_web")

# ============ 公开端点（无需认证） ============
# auth 模块：login 不需要 auth，其他端点在函数签名里各自加 Depends(require_auth)
router.include_router(auth_router, prefix="/auth", tags=["auth"])
# 库存公开缩略图
router.include_router(inventory_public_router, prefix="/inventory", tags=["inventory-public"])

# ============ 需要认证的端点 ============
_AUTH = [Depends(require_auth)]

router.include_router(system_router, prefix="/system", tags=["system"], dependencies=_AUTH)
router.include_router(ssl_mitm_router, prefix="/ssl-mitm", tags=["ssl-mitm"], dependencies=_AUTH)
router.include_router(ocr_router, prefix="/ocr", tags=["ocr"], dependencies=_AUTH)
router.include_router(scan_router, prefix="/scan", tags=["scan"], dependencies=_AUTH)
router.include_router(categories_router, prefix="/categories", tags=["categories"], dependencies=_AUTH)
router.include_router(transactions_router, prefix="/transactions", tags=["transactions"], dependencies=_AUTH)
router.include_router(product_types_router, prefix="/product-types", tags=["product-types"], dependencies=_AUTH)
router.include_router(
    ptcm_router,
    prefix="/product-type-category-mappings",
    tags=["product-type-category-mappings"],
    dependencies=_AUTH,
)
router.include_router(app_config_router, prefix="/app-config", tags=["app-config"], dependencies=_AUTH)
router.include_router(cost_records_router, prefix="/cost-records", tags=["cost-records"], dependencies=_AUTH)
router.include_router(cost_expenses_router, prefix="/cost-expenses", tags=["cost-expenses"], dependencies=_AUTH)
router.include_router(warehouses_router, prefix="/warehouses", tags=["warehouses"], dependencies=_AUTH)
router.include_router(web_drive_router, prefix="/web-drive", tags=["web-drive"], dependencies=_AUTH)
router.include_router(on_sale_items_router, prefix="/on-sale-items", tags=["on-sale-items"], dependencies=_AUTH)
router.include_router(orders_router, prefix="/orders", tags=["orders"], dependencies=_AUTH)
router.include_router(inventory_router, prefix="/inventory", tags=["inventory"], dependencies=_AUTH)
router.include_router(meilu_accounts_router, prefix="/meilu-accounts", tags=["meilu-accounts"], dependencies=_AUTH)
