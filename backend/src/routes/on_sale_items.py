# -*- coding: utf-8 -*-
from typing import Dict, Optional, Set
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel

from ..db_manage.database import DatabaseManager
from ..db_manage.models.on_sale_item import OnSaleItemModel
from ..db_manage.models.warehouse import WarehouseModel
from ..operation_mercari.on_sale_item_detail_sync import fetch_detail_and_sync_inventory
from ..operation_mercari.on_sale_items_sync import sync_on_sale_items_from_mercari
from ..operation_mercari.sync_data import resolve_account_id_by_seller_id

router = APIRouter(prefix="/api/on-sale-items", tags=["on-sale-items"])
_MERCARI_ID_SEP_RE = re.compile(r"[\n,，、\s]+")


def _split_mercari_item_ids(raw) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    out = []
    seen = set()
    for part in _MERCARI_ID_SEP_RE.split(s):
        t = str(part or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _seller_name_by_seller_id(seller_ids: Set[str]) -> Dict[str, str]:
    """按 seller_id 从 meilu_accounts 取展示名（account_name），键为 TRIM 后的 seller_id。"""
    ids = {str(s).strip() for s in seller_ids if s is not None and str(s).strip()}
    if not ids:
        return {}
    db = DatabaseManager()
    lst = list(ids)
    ph = ",".join(["?"] * len(lst))
    sql = f"""
        SELECT TRIM(COALESCE([seller_id], '')), [account_name], [status], [id]
        FROM [meilu_accounts]
        WHERE TRIM(COALESCE([seller_id], '')) IN ({ph})
        ORDER BY CASE WHEN [status] = 'active' THEN 0 ELSE 1 END, [id] ASC
    """
    rows = db.execute_query(sql, tuple(lst))
    out: Dict[str, str] = {}
    for sid, aname, _status, _id in rows:
        if sid and sid not in out:
            out[sid] = (aname or "").strip()
    return out


def _attach_seller_name(items: list) -> None:
    if not items:
        return
    sid_set = {str(i.get("seller_id") or "").strip() for i in items}
    name_map = _seller_name_by_seller_id(sid_set)
    for row in items:
        sid = str(row.get("seller_id") or "").strip()
        row["seller_name"] = name_map.get(sid) or None


def _attach_inventory_by_item_id(items: list) -> None:
    """按煤炉 item_id 与 inventory.mercari_item_id 匹配，附加库存位置与数量（支持一对多）。"""
    def _to_int(v, default=0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    if not items:
        return
    raw = list(
        {
            str(i.get("item_id") or "").strip()
            for i in items
            if str(i.get("item_id") or "").strip()
        }
    )
    if not raw:
        return
    db = DatabaseManager()
    _wh_w = WarehouseModel.sql_display_label("w")
    sql = f"""
        SELECT
            i.[mercari_item_id],
            i.[id],
            IFNULL(i.[name], ''),
            i.[quantity],
            i.[on_sale_quantity],
            TRIM(IFNULL(i.[barcode], '')),
            {_wh_w},
            IFNULL(w.[location], '')
        FROM [inventory] i
        LEFT JOIN [warehouses] w ON w.[id] = i.[warehouse_id]
        WHERE TRIM(IFNULL(i.[mercari_item_id], '')) != ''
    """
    rows = db.execute_query(sql)
    by_mid: Dict[str, list] = {}
    wanted = set(raw)
    for mids_raw, iid, iname, qty, osq, barcode, wname, wloc in rows:
        mids = _split_mercari_item_ids(mids_raw)
        if not mids:
            continue
        payload = (iid, iname, qty, osq, barcode, wname, wloc)
        for k in mids:
            if k in wanted:
                by_mid.setdefault(k, []).append(payload)
    for row in items:
        k = str(row.get("item_id") or "").strip()
        hits = by_mid.get(k)
        if hits is None and k.startswith("m"):
            hits = by_mid.get(k[1:])
        if hits is None and k.isdigit():
            hits = by_mid.get("m" + k)
        if hits:
            first = hits[0]
            row["inventory_id"] = int(first[0]) if first[0] is not None else None
            # first: (iid, iname, qty, osq, barcode, wname, wloc)
            row["inventory_quantity"] = _to_int(first[2], 0)
            row["inventory_on_sale_quantity"] = _to_int(first[3], 0)
            loc_parts = []
            mgmt_id_parts = []
            barcode_parts = []
            product_name_parts = []
            inventory_lines = []
            for iid, iname, qty, osq, barcode, wname, wloc in hits:
                loc_name = str(wname or "").strip() or str(wloc or "").strip() or "-"
                loc_parts.append(
                    f"#{int(iid)} {loc_name} x{int(osq) if osq is not None else 0}"
                )
                mgmt_id_parts.append(str(int(iid)))
                bc = str(barcode or "").strip()
                if bc:
                    barcode_parts.append(bc)
                n = str(iname or "").strip()
                if n:
                    product_name_parts.append(n)
                inventory_lines.append(
                    {
                        "management_id": str(int(iid)),
                        "barcode": bc or None,
                        "location": loc_name,
                        "on_sale_quantity": _to_int(osq, 0),
                        "product_name": n or None,
                    }
                )
            row["inventory_match_count"] = len(hits)
            row["inventory_locations_text"] = "、".join(loc_parts)
            row["inventory_mgmt_ids_text"] = "、".join(mgmt_id_parts)
            row["inventory_barcodes_text"] = "、".join(barcode_parts)
            row["inventory_product_names_text"] = "、".join(product_name_parts)
            row["inventory_lines"] = inventory_lines
        else:
            row["inventory_id"] = None
            row["inventory_quantity"] = None
            row["inventory_on_sale_quantity"] = None
            row["inventory_match_count"] = 0
            row["inventory_locations_text"] = None
            row["inventory_mgmt_ids_text"] = None
            row["inventory_barcodes_text"] = None
            row["inventory_product_names_text"] = None
            row["inventory_lines"] = []


def _is_on_sale_zero_stock_alert(row: dict) -> bool:
    """与前端一致：status=on_sale 且 inventory_quantity<=0 或 None 时标红。
    前端 Number(null)==0，故 null 也视为缺货预警。
    """
    status = str(row.get("status") or "").strip()
    if status != "on_sale":
        return False
    raw = row.get("inventory_quantity")
    if raw is None:
        # 未匹配到库存记录，前端 Number(null)==0 → 标红
        return True
    try:
        return float(raw) <= 0
    except (TypeError, ValueError):
        return False


def _on_sale_sort_key(row: dict) -> tuple:
    """
    在售列表排序键（全表维度）：
    1) 标红项优先（on_sale 且 inventory_quantity<=0）
    2) 其余按更新时间倒序
    3) 再按创建时间倒序
    4) 最后按 id 倒序兜底，保证稳定
    """
    return (
        0 if _is_on_sale_zero_stock_alert(row) else 1,
        -int(row.get("updated") or 0),
        -int(row.get("created") or 0),
        -int(row.get("id") or 0),
    )


def _sort_on_sale_items_for_alert(items: list[dict]) -> None:
    """
    原地排序（全量）：
    1) 先将标红项与非标红项拆分，保证标红组整体在前
    2) 各组内按更新时间/创建时间/id 倒序
    """
    alerts = [r for r in items if _is_on_sale_zero_stock_alert(r)]
    others = [r for r in items if not _is_on_sale_zero_stock_alert(r)]
    # 组内倒序：这里复用原有 key，避免时间并列时不稳定
    alerts.sort(key=_on_sale_sort_key)
    others.sort(key=_on_sale_sort_key)
    items[:] = alerts + others


class SyncOnSaleRequest(PydanticModel):
    account_id: Optional[int] = None


class FetchOnSaleDetailRequest(PydanticModel):
    """items/get 拉取详情并尝试同步库存；account_id 不传则按在售行的 seller_id 匹配 active 账号。"""
    item_id: str
    account_id: Optional[int] = None


@router.get("")
def list_on_sale_items(
    keyword: Optional[str] = None,
    seller_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    # 后端全表排序：先取全部匹配项，补齐库存字段后按“标红优先”排序，再做分页切片。
    all_items = []
    fetch_page = 1
    fetch_size = 500
    while True:
        chunk = OnSaleItemModel.find_list(
            keyword=keyword,
            seller_id=seller_id,
            status=status,
            page=fetch_page,
            page_size=fetch_size,
        )
        rows = chunk.get("items") or []
        all_items.extend(rows)
        total = int(chunk.get("total") or 0)
        if not rows or len(all_items) >= total:
            break
        fetch_page += 1

    _attach_seller_name(all_items)
    _attach_inventory_by_item_id(all_items)

    _sort_on_sale_items_for_alert(all_items)

    total = len(all_items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": all_items[start:end],
    }


@router.get("/by-item-id")
def list_on_sale_by_item_id(item_id: str):
    """
    按煤炉商品 ID 查询本地 on_sale_items（用于二级表格明细）。
    """
    iid = (item_id or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="item_id 不能为空")
    items = OnSaleItemModel.find_all_by_item_id(iid)
    _attach_seller_name(items)
    _attach_inventory_by_item_id(items)
    return {"item_id": iid, "total": len(items), "items": items}


@router.get("/by-item-ids")
def list_on_sale_by_item_ids(item_ids: str):
    """
    按多个煤炉商品 ID 查询本地 on_sale_items（用于库存页展开批量展示）。
    item_ids 支持逗号/空白分隔。
    """
    ids = _split_mercari_item_ids(item_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="item_ids 不能为空")
    items = OnSaleItemModel.find_all_by_item_ids(ids)
    _attach_seller_name(items)
    _attach_inventory_by_item_id(items)
    return {"item_ids": ids, "total": len(items), "items": items}


@router.post("/sync")
def sync_on_sale(data: SyncOnSaleRequest):
    """
    从煤炉拉取在售列表（items/get_items，status=on_sale,stop 等）并同步本地：
    新列表中不存在的本地记录不物理删除，而是标记 is_delete=1（软删除）。
    列表接口默认仅返回 is_delete=0 数据。须配置 dpop_on_sale_list。
    """
    try:
        result = sync_on_sale_items_from_mercari(account_id=data.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步失败: {exc}") from exc
    return {"success": True, "data": result}


@router.post("/fetch-detail")
def fetch_on_sale_item_detail(data: FetchOnSaleDetailRequest):
    """
    GET api.mercari.jp/items/get（完整 include_* 查询串），须配置 dpop_item_get_info。
    解析 data.description 中的「管理ID / 管理番号 / バーコード」，匹配库存后写入 mercari_item_id、on_sale_quantity。
    """
    item_id = (data.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    account_id = data.account_id
    if account_id is None:
        rows = OnSaleItemModel.find_all(
            where="TRIM([item_id]) = TRIM(?)",
            params=(item_id,),
            limit=1,
        )
        seller_id = None
        if rows:
            seller_id = str(rows[0].seller_id or "").strip() or None
        if seller_id:
            account_id = resolve_account_id_by_seller_id(seller_id)
        if account_id is None:
            raise HTTPException(
                status_code=400,
                detail="请传 account_id，或在在售列表中存在该商品且卖家已绑定 active 煤炉账号（seller_id）",
            )

    try:
        payload = fetch_detail_and_sync_inventory(item_id, account_id=account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {exc}") from exc

    return {"success": True, "data": payload}
