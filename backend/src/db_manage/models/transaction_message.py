# -*- coding: utf-8 -*-
"""
交易消息/交流缓存表。

按「订单ID」(order_no == todo_items.item_id == orders.order_no) 关联存储，
每条消息一行（规范化）。与 todo_items 行的生命周期解耦：待办被软删/重新同步后，
该订单的交流历史仍保留，可按订单查询。

消息内容此前内嵌在 todo_items.detail_json 的 messages 数组里；本表为消息的唯一来源，
旧数据由 db_manager 的一次性迁移搬入（见 _migrate_todo_messages_to_table）。
"""

from typing import Any, Dict, List

from ..base_model import BaseModel


class TransactionMessageModel(BaseModel):
    """交易消息（按订单ID关联）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "transaction_messages"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 订单ID（= todo_items.item_id = orders.order_no）
            "order_no": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "account_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 煤炉消息 id（用于复用已下载的本地图；部分消息可能无 id）
            "msg_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 发信人显示名（消息 user.name）
            "sender_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 发信人煤炉 user id
            "user_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "is_buyer": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "text": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 中文译文（仅买家消息、抓取时经谷歌翻译生成；旧数据为 NULL）
            "text_zh": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 本地 /imges 路径列表（JSON 字符串）
            "images_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # emoji 反应 key（heart/smile/...）或煤炉返回的短名
            "reaction": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 展示用时间字符串（"%Y-%m-%d %H:%M"，与抓取时一致）
            "at_text": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 消息创建时间（毫秒），用于排序；迁移的旧数据可能为 0/空
            "created_ms": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 同一订单内的稳定排序下标（created_ms 缺失/相同时的兜底排序）
            "sort_index": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            # 写入时间（毫秒）
            "synced_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {"name": "idx_tx_messages_order_no", "columns": ["order_no"]},
            {"name": "idx_tx_messages_order_msg", "columns": ["order_no", "msg_id"]},
        ]
