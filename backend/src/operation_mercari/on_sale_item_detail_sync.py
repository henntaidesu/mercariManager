# -*- coding: utf-8 -*-
"""
在售商品详情：经网页 ``jp.mercari.com/item/m…`` + MITM 截获 items/get 响应，
解析说明中的管理番号 / バーコード → 回写 inventory.mercari_item_id、on_sale_quantity。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..db_manage.database import DatabaseManager
from .get_order.description_mgmt_ids import (
    _inventory_id_by_barcode,
    _inventory_id_exists,
    parse_order_description_outbound_tokens,
)
from .get_order.mercari_item_get import fetch_mercari_item_get

_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_MGMT_ID_PATTERN = re.compile(r"管理\s*ID\s*[:：]\s*([0-9０-９\s,，、*xX×]+)", re.IGNORECASE | re.MULTILINE)
_MGMT_BANGO_PATTERN = re.compile(r"管理\s*番号\s*[:：]\s*([0-9０-９\s,，、*xX×]+)", re.MULTILINE)
_BARCODE_PATTERN = re.compile(
    r"バーコード\s*[:：]\s*([0-9A-Za-z０-９\s,，、\-_*xX×]+)",
    re.MULTILINE,
)

_MERCARI_ID_SEP_RE = re.compile(r"[\n,，、\s]+")


def _mercari_response_ok(resp: Any) -> bool:
    if not isinstance(resp, dict):
        return False
    rc = resp.get("result")
    if rc is None:
        return isinstance(resp.get("data"), dict)
    return str(rc).strip().upper() == "OK"


def _on_sale_quantity_from_status(status: Optional[str]) -> int:
    """煤炉 status=on_sale（出售中）计 1 件在售；暂停/交易中/已售等均为 0。"""
    s = (status or "").strip()
    return 1 if s == "on_sale" else 0


def _normalize_mercari_item_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    t = str(raw).strip()
    return t or None


def _split_mercari_item_ids(raw: Any) -> List[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    out: List[str] = []
    seen = set()
    for part in _MERCARI_ID_SEP_RE.split(s):
        t = str(part or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _join_mercari_item_ids(ids: List[str]) -> Optional[str]:
    arr = []
    seen = set()
    for v in ids:
        t = str(v or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        arr.append(t)
    return "、".join(arr) if arr else None


def _split_chunks(segment: str) -> List[str]:
    parts: List[str] = []
    for part in re.split(r"[,，、\s]+", segment or ""):
        p = (part or "").strip()
        if p:
            parts.append(p)
    return parts


def _value_and_quantity(token: str) -> Tuple[str, int]:
    """
    支持 token 尾部数量语法：6977850080862*10 / 6977850080862×10 / 6977850080862x10。
    未携带数量时默认 1。
    """
    t = (token or "").translate(_FW_DIGITS).strip()
    if not t:
        return "", 1
    m = re.match(r"^(.*?)(?:\s*[*xX×]\s*(\d+))?$", t)
    if not m:
        return t, 1
    base = (m.group(1) or "").strip()
    qraw = (m.group(2) or "").strip()
    if not qraw:
        return base, 1
    try:
        q = int(qraw)
    except (TypeError, ValueError):
        q = 1
    return base, max(1, q)


def parse_listing_description_tokens_with_quantity(text: Optional[str]) -> List[Dict[str, Any]]:
    """
    解析说明中的管理番号/条码，并保留每个识别值对应数量。
    返回项：{kind: mgmt_id|barcode, value: int|str, quantity: int, raw: str}
    """
    if text is None:
        return []
    s = str(text).strip()
    if not s:
        return []
    spans: List[Tuple[int, str, str]] = []
    for m in _MGMT_ID_PATTERN.finditer(s):
        spans.append((m.start(), "mgmt", m.group(1) or ""))
    for m in _MGMT_BANGO_PATTERN.finditer(s):
        spans.append((m.start(), "mgmt", m.group(1) or ""))
    for m in _BARCODE_PATTERN.finditer(s):
        spans.append((m.start(), "barcode", m.group(1) or ""))
    spans.sort(key=lambda x: x[0])

    out: List[Dict[str, Any]] = []
    for _, kind, chunk in spans:
        for part in _split_chunks(chunk):
            base, qty = _value_and_quantity(part)
            if not base:
                continue
            if kind == "mgmt":
                try:
                    mid = int(base)
                except (TypeError, ValueError):
                    continue
                out.append({"kind": "mgmt_id", "value": mid, "quantity": qty, "raw": part})
            else:
                out.append({"kind": "barcode", "value": str(base).strip(), "quantity": qty, "raw": part})
    return out


def resolve_inventory_id_from_listing_description(text: Optional[str]) -> Optional[int]:
    """
    按说明文中出现顺序，找第一个可映射到本地库存的标识：
    管理 ID / 管理番号 → inventory.id；バーコード → inventory.barcode。
    """
    tokens: List[Tuple[str, Any]] = parse_order_description_outbound_tokens(text)
    for kind, val in tokens:
        if kind == "mgmt_id":
            mid = int(val)
            if _inventory_id_exists(mid):
                return mid
        else:
            bc = str(val).strip()
            inv_id = _inventory_id_by_barcode(bc)
            if inv_id is not None:
                return inv_id
    return None


def extract_mgmt_barcode_hints(text: Optional[str]) -> Dict[str, Any]:
    """便于前端展示：从说明中抽取的管理番号（数字串）与条码串列表（不要求已存在于库）。"""
    tokens = parse_order_description_outbound_tokens(text)
    mgmt: List[int] = []
    barcodes: List[str] = []
    for kind, val in tokens:
        if kind == "mgmt_id":
            mgmt.append(int(val))
        else:
            barcodes.append(str(val).strip())
    return {"management_numbers": mgmt, "barcodes": barcodes}


def fetch_detail_and_sync_inventory(
    item_id: str,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    通过浏览器打开商品页并由 MITM 截获 items/get，将 data.id 与在售数量写入匹配到的库存行。

    :return: { api: 原始响应, sync: { updated, inventory_id, mercari_item_id, on_sale_quantity, message } }
    """
    resp = fetch_mercari_item_get(item_id, account_id=account_id)
    sync: Dict[str, Any] = {
        "updated": False,
        "inventory_id": None,
        "mercari_item_id": None,
        "on_sale_quantity": None,
        "message": None,
    }

    if not _mercari_response_ok(resp):
        sync["message"] = "煤炉接口返回非 OK"
        return {"api": resp, "sync": sync}

    data = resp.get("data")
    if not isinstance(data, dict):
        sync["message"] = "响应缺少 data"
        return {"api": resp, "sync": sync}

    desc = data.get("description")
    desc_text = desc if isinstance(desc, str) else None
    inv_id = resolve_inventory_id_from_listing_description(desc_text)
    mid_api = _normalize_mercari_item_id(data.get("id"))
    status = data.get("status")
    on_sale_qty = _on_sale_quantity_from_status(status if isinstance(status, str) else None)

    hints = extract_mgmt_barcode_hints(desc_text)
    sync["parsed_hints"] = hints
    parsed_tokens = parse_listing_description_tokens_with_quantity(desc_text)
    sync["parsed_tokens"] = parsed_tokens

    if inv_id is None:
        sync["message"] = (
            "说明中未找到可关联的库存（需「管理ID」「管理番号」对应已存在的库存 id，"
            "或「バーコード」对应已存在的库存条码）"
        )
        return {"api": resp, "sync": sync}

    if not mid_api:
        sync["message"] = "响应中缺少商品 id"
        return {"api": resp, "sync": sync}

    resolved_lines: List[Dict[str, Any]] = []
    qty_by_inventory: Dict[int, int] = {}
    for token in parsed_tokens:
        kind = str(token.get("kind") or "")
        value = token.get("value")
        qty = int(token.get("quantity") or 1)
        resolved_inv_id: Optional[int] = None
        if kind == "mgmt_id":
            mid = int(value)
            if _inventory_id_exists(mid):
                resolved_inv_id = mid
        elif kind == "barcode":
            resolved_inv_id = _inventory_id_by_barcode(str(value or "").strip())
        resolved_lines.append(
            {
                "kind": kind,
                "value": value,
                "quantity": qty,
                "inventory_id": resolved_inv_id,
            }
        )
        if resolved_inv_id is not None:
            qty_by_inventory[resolved_inv_id] = qty_by_inventory.get(resolved_inv_id, 0) + qty

    if not qty_by_inventory and inv_id is not None:
        # 回退兼容：若解析列表为空但旧逻辑能识别到单个库存，按 status 推导 0/1。
        qty_by_inventory[int(inv_id)] = max(0, int(on_sale_qty))
    sync["resolved_lines"] = resolved_lines

    db = DatabaseManager()
    try:
        current_rows = db.execute_query(
            """
            SELECT [id], [mercari_item_id], [on_sale_quantity]
            FROM [inventory]
            WHERE TRIM(IFNULL([mercari_item_id], '')) != ''
            """
        )
        matched_ids = set(int(i) for i in qty_by_inventory.keys())
        for iid_raw, mids_raw, osq_raw in current_rows:
            iid = int(iid_raw)
            mids = _split_mercari_item_ids(mids_raw)
            if not mids:
                continue
            if mid_api in mids and iid not in matched_ids:
                # 同一煤炉商品上次关联但本次未命中的库存：仅移除该 mid，不破坏该库存绑定的其他 mid。
                next_mids = [x for x in mids if x != mid_api]
                next_mid_text = _join_mercari_item_ids(next_mids)
                next_osq = 0 if not next_mids else int(osq_raw or 0)
                db.execute_update(
                    """
                    UPDATE [inventory]
                    SET [mercari_item_id] = ?, [on_sale_quantity] = ?
                    WHERE [id] = ?
                    """,
                    (next_mid_text, next_osq, iid),
                )
        for iid, qty in qty_by_inventory.items():
            row = db.execute_query(
                "SELECT [mercari_item_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
                (int(iid),),
            )
            old_mids = _split_mercari_item_ids(row[0][0] if row else None)
            if mid_api not in old_mids:
                old_mids.append(mid_api)
            merged_mid_text = _join_mercari_item_ids(old_mids)
            db.execute_update(
                """
                UPDATE [inventory]
                SET [mercari_item_id] = ?, [on_sale_quantity] = ?
                WHERE [id] = ?
                """,
                (merged_mid_text, int(qty), int(iid)),
            )
    except Exception as exc:
        sync["message"] = f"写入库存失败: {exc}"
        return {"api": resp, "sync": sync}

    sync["updated"] = bool(qty_by_inventory)
    sync["inventory_id"] = int(inv_id) if inv_id is not None else None
    sync["mercari_item_id"] = mid_api
    sync["on_sale_quantity"] = sum(qty_by_inventory.values()) if qty_by_inventory else 0
    sync["inventory_ids"] = sorted(qty_by_inventory.keys())
    sync["inventory_quantity_map"] = {str(k): int(v) for k, v in qty_by_inventory.items()}
    sync["message"] = "已同步煤炉商品 ID 与在售数量" if qty_by_inventory else "未匹配到可写入库存"
    return {"api": resp, "sync": sync}
