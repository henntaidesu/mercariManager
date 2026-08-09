# -*- coding: utf-8 -*-
"""雅虎 App（sparkle）API 的 OAuth 令牌，按店铺账号一行。

单独建表而不是塞进 ``shop_accounts.value``：那一列由 ``_norm_headers_dict`` 按白名单重写，
任何一次账号编辑都会把不在白名单里的键丢掉——而这里的 access_token 是**会自动轮换**的
（每次刷新雅虎都下发新的 refresh_token），令牌写入与账号编辑必须互不干扰。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class YahooAppTokenModel(BaseModel):
    """雅虎 App API 令牌"""

    @classmethod
    def get_table_name(cls) -> str:
        return "yahoo_app_tokens"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "account_id": {
                "type": "INTEGER",
                "not_null": True,
                "default": None,
            },
            "access_token": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 雅虎每次刷新都下发新的 refresh_token，旧的随即失效——刷新成功必须整体回写。
            "refresh_token": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # access_token 过期时刻（epoch 毫秒）。0/NULL = 未知，按「已过期」处理先刷一次。
            "expires_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            # App 抓包里的 X-UUID / X-BCOOKIE。雅虎不校验其内容，但同一账号固定用同一组更像真实设备。
            "device_uuid": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "bcookie": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "updated_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": "idx_yahoo_app_tokens_account",
                "columns": ["account_id"],
                "unique": True,
            },
        ]
