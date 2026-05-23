# -*- coding: utf-8 -*-
"""
mercariV2 API 根模块

层级蓝图注册：
- 从 main.py 接收前缀 /mercariV2
- 向下传递给 use_web 模块（前端 API），添加 /src 路径段
- 向下传递给 operation_mercari 模块（Mercari 业务编排），添加 /src 路径段
- 完整 URL 格式: /mercariV2/src/<module>/<endpoint>
"""

from fastapi import APIRouter, Depends

from .auth import require_auth
from .use_web.API import router as use_web_router
from .operation_mercari.API import router as operation_mercari_router

router = APIRouter()


def _health():
    """健康检查，用于更新后轮询确认 Backend 已启动。"""
    return {"status": "ok", "service": "mercari-backend"}


router.add_api_route("/health", _health, methods=["GET"])

# /mercariV2/src/use_web/...
router.include_router(use_web_router, prefix="/src")

# /mercariV2/src/operation_mercari/...（前端可调用，需 auth）
router.include_router(
    operation_mercari_router,
    prefix="/src",
    dependencies=[Depends(require_auth)],
)
