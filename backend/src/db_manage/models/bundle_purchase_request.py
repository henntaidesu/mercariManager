# -*- coding: utf-8 -*-
"""
合并购买请求（Mercari /bundle_offer/{bundle_id} 页对应 v1/bundlePurchases API 响应）本地缓存表。

字段与 backend/test_json/待办/商品详情/组合出售依赖.json 中顶层对齐：
- name=bundle_id（URL 末段，UPSERT key 与 account_id 组合唯一）
- seller_id / buyer_id / buyer_username / suggested_price / original_price / state
- items 数组整体 JSON 保留，单独不拆字段（前端按需渲染）
- createTime / expireTime 转毫秒便于排序与过期判断

另：本表同时存放用户在合并购买详情弹窗中填写的「出品表单」选择
（送料负担 / 配送方法 / 发货地 / 发货天数），点击提交前先落盘。
"""

from typing import Any, Dict, List

from ..base_model import BaseModel


class BundlePurchaseRequestModel(BaseModel):
    """合并购买请求缓存 + 出品表单选择"""

    @classmethod
    def get_table_name(cls) -> str:
        return "bundle_purchase_requests"

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
            "bundle_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "notification_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "seller_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "buyer_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "buyer_username": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "suggested_price": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "original_price": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "state": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "items_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "raw_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "bundle_created": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "bundle_expire": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 用户在详情弹窗填写的出品表单选择（点击「依頼を承諾する」前先持久化）
            "form_shipping_payer": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "form_shipping_method": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "form_shipping_from": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "form_shipping_days": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "form_updated_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "synced_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": "idx_bundle_purchases_account_bundle",
                "columns": ["account_id", "bundle_id"],
                "unique": True,
            },
            {"name": "idx_bundle_purchases_notification_id", "columns": ["notification_id"]},
            {"name": "idx_bundle_purchases_state", "columns": ["state"]},
            {"name": "idx_bundle_purchases_created", "columns": ["bundle_created"]},
        ]
