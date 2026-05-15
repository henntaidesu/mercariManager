# -*- coding: utf-8 -*-
"""Web 自动化：按账号隔离的 Microsoft Edge 持久化会话（Cookie 随 profile 保存）。"""

from .account_serial_queue import (
    GLOBAL_QUEUE_KEY,
    queue_key_for_meilu_account,
    resolve_meilu_account_id,
    run_meilu_serial_async,
    shutdown_serial_executors,
)
from .manager import EdgeWebDriveManager, get_web_drive_manager
from .paths import (
    meilu_account_key,
    meilu_automation_key,
    profile_dir_for,
    profiles_root,
    seed_automation_profile_from_account,
    validate_account_key,
)

__all__ = [
    "EdgeWebDriveManager",
    "GLOBAL_QUEUE_KEY",
    "get_web_drive_manager",
    "meilu_account_key",
    "meilu_automation_key",
    "profile_dir_for",
    "seed_automation_profile_from_account",
    "profiles_root",
    "queue_key_for_meilu_account",
    "resolve_meilu_account_id",
    "run_meilu_serial_async",
    "shutdown_serial_executors",
    "validate_account_key",
]
