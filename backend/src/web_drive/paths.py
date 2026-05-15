# -*- coding: utf-8 -*-
"""Edge 持久化用户数据目录（Cookie / LocalStorage 等随 profile 落盘）。"""

from __future__ import annotations

import logging
import os
import re
import shutil
from typing import List, Optional

from src.app_paths import backend_root_str

log = logging.getLogger(__name__)

_ACCOUNT_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_MEILU_AUTO_SUFFIX = "__auto"

# 从主 profile 复制到 __auto，尽量带上煤炉登录态（主窗口打开时部分文件可能被锁，跳过即可）
_AUTH_SEED_REL_PATHS: List[str] = [
    os.path.join("Default", "Cookies"),
    os.path.join("Default", "Cookies-journal"),
    os.path.join("Default", "Login Data"),
    os.path.join("Default", "Login Data For Account"),
    os.path.join("Default", "Login Data-journal"),
    os.path.join("Default", "Login Data For Account-journal"),
    os.path.join("Default", "Preferences"),
    os.path.join("Default", "Secure Preferences"),
    os.path.join("Default", "Network"),
    os.path.join("Default", "Local Storage"),
    os.path.join("Default", "Session Storage"),
    os.path.join("Default", "IndexedDB"),
]


def backend_root() -> str:
    return backend_root_str()


def profiles_root() -> str:
    override = (os.environ.get("WEB_DRIVE_PROFILES_DIR") or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(backend_root(), "data", "web_drive_profiles")


def validate_account_key(account_key: str) -> str:
    s = (account_key or "").strip()
    if not _ACCOUNT_KEY_RE.match(s):
        raise ValueError(
            "account_key 须为 1～64 位，仅允许字母、数字、下划线、连字符（用于隔离不同子浏览器配置）"
        )
    return s


def profile_dir_for(account_key: str) -> str:
    key = validate_account_key(account_key)
    root = profiles_root()
    path = os.path.join(root, key)
    os.makedirs(path, exist_ok=True)
    return path


def meilu_account_key(account_id: int) -> str:
    """账号管理 / 库存出品：有头可见浏览器 profile（用户手动登录）。"""
    return f"meilu_{int(account_id)}"


def meilu_automation_key(account_id: int) -> str:
    """订单更新列表/状态、在售同步、MITM 抓包：独立无头 profile，与有头窗口并行。"""
    return f"meilu_{int(account_id)}{_MEILU_AUTO_SUFFIX}"


def meilu_id_from_account_key(account_key: str) -> Optional[int]:
    key = (account_key or "").strip()
    if not key.startswith("meilu_"):
        return None
    tail = key[6:]
    if tail.endswith(_MEILU_AUTO_SUFFIX):
        tail = tail[: -len(_MEILU_AUTO_SUFFIX)]
    try:
        return int(tail)
    except ValueError:
        return None


def seed_automation_profile_from_account(account_id: int) -> None:
    """
    将 ``meilu_{id}`` 主 profile 的登录相关文件同步到 ``meilu_{id}__auto``，
    供无头 MITM 使用（主 profile 正被有头 Edge 占用时可能部分复制失败，忽略即可）。
    """
    main_key = meilu_account_key(account_id)
    auto_key = meilu_automation_key(account_id)
    src_root = profile_dir_for(main_key)
    dst_root = profile_dir_for(auto_key)
    os.makedirs(os.path.join(dst_root, "Default"), exist_ok=True)

    for rel in _AUTH_SEED_REL_PATHS:
        src = os.path.join(src_root, rel)
        dst = os.path.join(dst_root, rel)
        if not os.path.exists(src):
            continue
        try:
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
        except Exception as exc:
            log.debug("seed automation profile skip %s: %s", rel, exc)
