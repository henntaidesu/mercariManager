# -*- coding: utf-8 -*-
"""Web 自动化：按账号隔离的 Microsoft Edge 持久化会话（Cookie 随 profile 保存）。

包结构（V2 重组）：
- core/    内部基础设施（manager / 队列 / paths / 浏览器 / MITM 会话）
- listing/ 出品业务（post_to_macket / 进度跟踪）
- revise/  改价业务
- delete/  删除业务

外部使用建议：
- 通用入口直接 `from src.web_drive import get_web_drive_manager` 等（本 __init__ 重导出）
- 具体内部模块按新路径 `from src.web_drive.core.X import ...`
- 业务模块按 `from src.web_drive.listing.units.post_to_macket import ...`
"""

from .core.account_serial_queue import (
    GLOBAL_QUEUE_KEY,
    queue_key_for_meilu_account,
    resolve_meilu_account_id,
    run_meilu_serial_async,
    shutdown_serial_executors,
)
from .core.manager import EdgeWebDriveManager, get_web_drive_manager
from .core.paths import (
    meilu_account_key,
    meilu_automation_key,
    meilu_listing_key,
    profile_dir_for,
    profiles_root,
    seed_automation_profile_from_account,
    seed_listing_profile_from_account,
    validate_account_key,
)

__all__ = [
    "EdgeWebDriveManager",
    "GLOBAL_QUEUE_KEY",
    "get_web_drive_manager",
    "meilu_account_key",
    "meilu_automation_key",
    "meilu_listing_key",
    "profile_dir_for",
    "seed_automation_profile_from_account",
    "seed_listing_profile_from_account",
    "profiles_root",
    "queue_key_for_meilu_account",
    "resolve_meilu_account_id",
    "run_meilu_serial_async",
    "shutdown_serial_executors",
    "validate_account_key",
]
