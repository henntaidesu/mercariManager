# -*- coding: utf-8 -*-
"""shared: detail cache read/write + uncached enumeration + qr path persist"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List
from ....db_manage.database import DatabaseManager
from ._common import _WAIT_REPLY_KINDS, _WAIT_REVIEW_KINDS, _WAIT_SHIPPING_KINDS, _WAIT_SHIPPING_TITLE

log = logging.getLogger(__name__)


def _persist_transaction_detail(todo_id: int, data: Dict[str, Any]) -> None:
    """把抓取到的交易详情整体缓存进 todo_items.detail_json（避免每次开浏览器重抓）。"""
    try:
        payload = json.dumps(data, ensure_ascii=False)
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [detail_json]=?, [detail_synced_at]=? WHERE [id]=?",
            (payload, int(time.time() * 1000), int(todo_id)),
        )
    except Exception as exc:
        log.warning("[txdetail] 缓存交易详情失败 todo_id=%s: %s", todo_id, exc)

def _persist_qr_image_path(todo_id: int, path: str) -> None:
    """保存二维码本地路径到 todo_items.qr_image_path，并同步写入已缓存的 detail_json。"""
    db = DatabaseManager()
    try:
        db.execute_update(
            "UPDATE [todo_items] SET [qr_image_path]=? WHERE [id]=?", (path, int(todo_id))
        )
        rows = db.execute_query(
            "SELECT [detail_json] FROM [todo_items] WHERE [id]=?", (int(todo_id),)
        )
        if rows and rows[0] and rows[0][0]:
            d = json.loads(rows[0][0])
            if isinstance(d, dict):
                d["qr_image_url"] = path
                db.execute_update(
                    "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                    (json.dumps(d, ensure_ascii=False), int(todo_id)),
                )
    except Exception as exc:
        log.warning("[shipping] 保存二维码路径失败 todo_id=%s: %s", todo_id, exc)

def _clear_qr_image(todo_id: int) -> None:
    """清除已保存的发货二维码：删除本地文件 + 清空 qr_image_path + 从 detail_json 摘掉。"""
    db = DatabaseManager()
    try:
        rows = db.execute_query(
            "SELECT [qr_image_path], [detail_json] FROM [todo_items] WHERE [id]=?",
            (int(todo_id),),
        )
        old_path = rows[0][0] if rows and rows[0] else None
        detail_json = rows[0][1] if rows and rows[0] else None
        db.execute_update(
            "UPDATE [todo_items] SET [qr_image_path]=NULL WHERE [id]=?", (int(todo_id),)
        )
        if detail_json:
            try:
                d = json.loads(detail_json)
                if isinstance(d, dict) and d.pop("qr_image_url", None) is not None:
                    db.execute_update(
                        "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                        (json.dumps(d, ensure_ascii=False), int(todo_id)),
                    )
            except Exception:
                pass
        if old_path:
            try:
                from ...use_web.image_storage import delete_image_file

                delete_image_file(old_path)
            except Exception:
                pass
    except Exception as exc:
        log.warning("[shipping] 清除二维码失败 todo_id=%s: %s", todo_id, exc)

def get_cached_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """读取 todo_items.detail_json 缓存（无浏览器）。无缓存返回 {}（仅含基础字段）。"""
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [detail_json], [detail_synced_at], [qr_image_path], [item_id], [item_name], [sender_id] "
            "FROM [todo_items] WHERE [id]=?",
            (int(todo_id),),
        )
    except Exception as exc:
        log.warning("[txdetail] 读取交易详情缓存失败 todo_id=%s: %s", todo_id, exc)
        return {}
    if not rows:
        return {}
    detail_json, synced_at, qr_path, item_id, item_name, sender_id = rows[0]
    data: Dict[str, Any] = {}
    if detail_json:
        try:
            parsed = json.loads(detail_json)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    data.setdefault("item_id", item_id or "")
    data.setdefault("item_name", item_name or "")
    data.setdefault("sender_id", sender_id or "")
    data["detail_synced_at"] = synced_at
    if qr_path and not data.get("qr_image_url"):
        data["qr_image_url"] = qr_path
    return data

def list_uncached_detail_todo_ids(account_id: int) -> List[int]:
    """返回某账号下「待发货」「待回复」「待评价」且尚无交易详情缓存的待办 id（供「从煤炉同步」后批量补抓详情）。

    判定「无缓存」：``detail_synced_at IS NULL``（fetch_transaction_detail 成功后才会写入）。
    仅含未软删 + 有 item_id 的待办（无 item_id 无法打开交易页）。
    """
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [id], [kind], [title] FROM [todo_items] "
            "WHERE [account_id]=? AND [is_delete]=0 "
            "AND [detail_synced_at] IS NULL "
            "AND [item_id] IS NOT NULL AND TRIM([item_id]) <> '' "
            "ORDER BY [mercari_updated] DESC",
            (int(account_id),),
        )
    except Exception as exc:
        log.warning("[txdetail] 查询未缓存待办失败 account_id=%s: %s", account_id, exc)
        return []
    ids: List[int] = []
    for row in rows or []:
        tid, kind, title = row
        kind = (kind or "").strip()
        title = (title or "").strip()
        if (
            kind in _WAIT_SHIPPING_KINDS
            or kind in _WAIT_REPLY_KINDS
            or kind in _WAIT_REVIEW_KINDS
            or title == _WAIT_SHIPPING_TITLE
        ):
            ids.append(int(tid))
    return ids
