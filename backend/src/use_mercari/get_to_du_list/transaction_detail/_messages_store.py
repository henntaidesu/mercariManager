# -*- coding: utf-8 -*-
"""交易消息（按订单ID关联）读写：transaction_messages 表的唯一访问层。

消息此前内嵌在 todo_items.detail_json.messages；现以本表为唯一来源，按 order_no
(= item_id = orders.order_no) 关联，与待办行生命周期解耦。

抓取交易详情时一次性拿到该订单的完整对话，故采用「按订单整体替换」(replace-all)：
先删该订单旧行再插入新行，天然去重、保序，无需 upsert。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager

log = logging.getLogger(__name__)


def _images_to_json(images: Any) -> str:
    paths = [p for p in (images or []) if isinstance(p, str) and p.strip()]
    return json.dumps(paths, ensure_ascii=False)


def replace_order_messages(
    order_no: str,
    account_id: Optional[int],
    messages: List[Dict[str, Any]],
) -> None:
    """按订单整体替换该订单的全部消息行（先删后插）。

    ``messages`` 为 ``_parse_messages`` 产出的展示态消息（图片已落地为本地 /imges 路径）。
    """
    ono = (order_no or "").strip()
    if not ono:
        return
    db = DatabaseManager()
    now_ms = int(time.time() * 1000)
    rows: List[tuple] = []
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        rows.append(
            (
                ono,
                int(account_id) if account_id is not None else None,
                (str(m.get("id")).strip() or None) if m.get("id") is not None else None,
                (m.get("from") or None),
                (m.get("user_id") or None),
                1 if m.get("is_buyer") else 0,
                (m.get("text") or ""),
                (m.get("text_zh") or None),
                _images_to_json(m.get("images")),
                (m.get("reaction") or None),
                (m.get("at") or None),
                int(m.get("created_ms") or 0),
                idx,
                now_ms,
            )
        )
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM [transaction_messages] WHERE TRIM([order_no])=TRIM(?)", (ono,))
            if rows:
                cur.executemany(
                    "INSERT INTO [transaction_messages] "
                    "([order_no],[account_id],[msg_id],[sender_name],[user_id],[is_buyer],"
                    "[text],[text_zh],[images_json],[reaction],[at_text],[created_ms],[sort_index],[synced_at]) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("[txmsg] 替换订单消息失败 order_no=%s: %s", ono, exc)


def load_order_messages(order_no: str) -> List[Dict[str, Any]]:
    """按订单读取消息，返回前端展示态列表（与旧 detail_json.messages 同结构）。"""
    ono = (order_no or "").strip()
    if not ono:
        return []
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [msg_id],[sender_name],[user_id],[is_buyer],[text],[text_zh],[images_json],"
            "[reaction],[at_text],[created_ms],[sort_index] "
            "FROM [transaction_messages] WHERE TRIM([order_no])=TRIM(?) "
            "ORDER BY COALESCE([created_ms],0) ASC, [sort_index] ASC, [id] ASC",
            (ono,),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("[txmsg] 读取订单消息失败 order_no=%s: %s", ono, exc)
        return []
    out: List[Dict[str, Any]] = []
    for msg_id, sender, uid, is_buyer, text, text_zh, images_json, reaction, at_text, created_ms, _sort in rows:
        try:
            images = json.loads(images_json) if images_json else []
            if not isinstance(images, list):
                images = []
        except Exception:
            images = []
        out.append(
            {
                "id": msg_id or None,
                "from": sender or None,
                "text": text or "",
                "text_zh": text_zh or None,
                "at": at_text or None,
                "is_buyer": bool(is_buyer),
                "user_id": uid or None,
                "reaction": reaction or None,
                "created_ms": int(created_ms or 0),
                "images": images,
            }
        )
    return out


def set_message_translation(
    order_no: str,
    msg_id: Optional[str],
    text: str,
    text_zh: str,
) -> bool:
    """把按需翻译得到的中文译文写回某条消息（旧数据按钮触发）。

    优先按 ``(order_no, msg_id)`` 定位；msg_id 缺失时按 ``(order_no, 原文)`` 命中一行
    （优先未翻译的）。命中并更新返回 True。
    """
    ono = (order_no or "").strip()
    if not ono or not (text_zh or "").strip():
        return False
    db = DatabaseManager()
    try:
        mid = (str(msg_id).strip() if msg_id is not None else "")
        if mid:
            n = db.execute_update(
                "UPDATE [transaction_messages] SET [text_zh]=? "
                "WHERE TRIM([order_no])=TRIM(?) AND [msg_id]=?",
                (text_zh, ono, mid),
            )
            if n:
                return True
        # 无 msg_id 或未命中：按原文定位一行（优先尚未翻译的）
        rows = db.execute_query(
            "SELECT [id] FROM [transaction_messages] "
            "WHERE TRIM([order_no])=TRIM(?) AND [text]=? "
            "ORDER BY ([text_zh] IS NOT NULL) ASC, [id] ASC LIMIT 1",
            (ono, text or ""),
        )
        if rows and rows[0]:
            db.execute_update(
                "UPDATE [transaction_messages] SET [text_zh]=? WHERE [id]=?",
                (text_zh, rows[0][0]),
            )
            return True
    except Exception as exc:  # noqa: BLE001
        log.warning("[txmsg] 写回译文失败 order_no=%s: %s", ono, exc)
    return False


def load_order_buyer_name(order_no: str) -> Optional[str]:
    """按订单推断买家名：优先首条买家消息的发信名，回退首条非空发信名（与解析逻辑一致）。"""
    ono = (order_no or "").strip()
    if not ono:
        return None
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [sender_name],[is_buyer] FROM [transaction_messages] "
            "WHERE TRIM([order_no])=TRIM(?) AND [sender_name] IS NOT NULL AND TRIM([sender_name])<>'' "
            "ORDER BY COALESCE([created_ms],0) ASC, [sort_index] ASC, [id] ASC",
            (ono,),
        )
    except Exception:
        return None
    first_any: Optional[str] = None
    for sender, is_buyer in rows:
        name = (sender or "").strip()
        if not name:
            continue
        if first_any is None:
            first_any = name
        if is_buyer:
            return name
    return first_any
