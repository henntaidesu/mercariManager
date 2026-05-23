# -*- coding: utf-8 -*-
"""认证相关 API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/auth
- 完整 URL 示例: POST /mercariV2/src/use_web/auth/login
"""

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel as PydanticModel

from ...auth import create_access_token, require_auth
from ...db_manage.database import DatabaseManager
from ...db_manage.models.user import UserModel

router = APIRouter()
db = DatabaseManager()


class LoginRequest(PydanticModel):
    username: str
    password: str


class UserCreateRequest(PydanticModel):
    username: str
    password: str
    display_name: str | None = None


class ChangePasswordRequest(PydanticModel):
    old_password: str
    new_password: str


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return digest.hex()


def _ensure_default_admin():
    UserModel.ensure_table_exists()
    user_count = db.execute_query("SELECT COUNT(*) FROM [users]")
    if user_count and user_count[0][0] > 0:
        return
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password("admin", salt_hex)
    db.execute_insert(
        """
        INSERT INTO [users] (username, password_hash, salt, display_name, is_active)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("admin", password_hash, salt_hex, "系统管理员", 1),
    )


@router.on_event("startup")
def startup_seed_user():
    _ensure_default_admin()


@router.post("/login")
def login(data: LoginRequest):
    username = (data.username or "").strip()
    password = data.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    rows = db.execute_query(
        """
        SELECT id, username, password_hash, salt, display_name, is_active
        FROM [users]
        WHERE username = ?
        LIMIT 1
        """,
        (username,),
    )
    if not rows:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user_id, db_username, db_hash, db_salt, display_name, is_active = rows[0]
    if not is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    if _hash_password(password, db_salt) != db_hash:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    db.execute_update(
        "UPDATE [users] SET last_login_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
    )

    return {
        "token": create_access_token(user_id, db_username),
        "user": {
            "id": user_id,
            "username": db_username,
            "display_name": display_name or db_username,
        },
    }


@router.get("/users")
def list_users(_claims: dict = Depends(require_auth)):
    rows = db.execute_query(
        """
        SELECT id, username, display_name, is_active, last_login_at, created_at
        FROM [users]
        ORDER BY id ASC
        """
    )
    keys = ["id", "username", "display_name", "is_active", "last_login_at", "created_at"]
    return [dict(zip(keys, row)) for row in rows]


@router.post("/users")
def create_user(data: UserCreateRequest, _claims: dict = Depends(require_auth)):
    username = (data.username or "").strip()
    password = data.password or ""
    display_name = (data.display_name or "").strip() or None
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")

    exists = db.execute_query("SELECT 1 FROM [users] WHERE username = ? LIMIT 1", (username,))
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")

    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(password, salt_hex)
    user_id = db.execute_insert(
        """
        INSERT INTO [users] (username, password_hash, salt, display_name, is_active)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, password_hash, salt_hex, display_name, 1),
    )
    return {
        "id": user_id,
        "username": username,
        "display_name": display_name or username,
        "is_active": 1,
    }


@router.post("/change-password")
def change_password(data: ChangePasswordRequest, claims: dict = Depends(require_auth)):
    user_id = int(claims.get("sub") or 0)
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    old_password = data.old_password or ""
    new_password = data.new_password or ""
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度至少6位")

    rows = db.execute_query(
        "SELECT password_hash, salt FROM [users] WHERE id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="用户不存在")
    db_hash, db_salt = rows[0]
    if _hash_password(old_password, db_salt) != db_hash:
        raise HTTPException(status_code=400, detail="原密码错误")

    new_salt = secrets.token_hex(16)
    new_hash = _hash_password(new_password, new_salt)
    db.execute_update(
        "UPDATE [users] SET password_hash = ?, salt = ? WHERE id = ?",
        (new_hash, new_salt, user_id),
    )
    return {"message": "密码修改成功"}
