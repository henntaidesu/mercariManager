# -*- coding: utf-8 -*-
"""在售商品列表 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/on_sale_items
- 完整 URL 示例: GET /mercariV2/src/use_web/on_sale_items/by-item-id
"""
from typing import Any, Dict, List, Optional, Set
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel

from ...db_manage.database import DatabaseManager
from ...db_manage.models.on_sale_item import OnSaleItemModel
from ...db_manage.models.warehouse import WarehouseModel
from ...web_drive.account_serial_queue import (
    queue_key_for_meilu_account,
    resolve_meilu_account_id,
    run_meilu_serial_async,
)
from ...operation_mercari.on_sale_item_detail_sync import fetch_detail_and_sync_inventory
from ...operation_mercari.on_sale_items_sync import (
    _is_active_on_sale,
    sync_on_sale_items_from_mercari,
)
from ...operation_mercari.sync_data import resolve_account_id_by_seller_id
from ...operation_mercari.get_order.description_mgmt_ids import (
    parse_management_ids_from_description,
)

router = APIRouter()
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
            inventory_name_parts = []
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
                    inventory_name_parts.append(n)
                inventory_lines.append(
                    {
                        "management_id": str(int(iid)),
                        "barcode": bc or None,
                        "location": loc_name,
                        "on_sale_quantity": _to_int(osq, 0),
                        "inventory_name": n or None,
                    }
                )
            row["inventory_match_count"] = len(hits)
            row["inventory_locations_text"] = "、".join(loc_parts)
            row["inventory_mgmt_ids_text"] = "、".join(mgmt_id_parts)
            row["inventory_barcodes_text"] = "、".join(barcode_parts)
            row["inventory_names_text"] = "、".join(inventory_name_parts)
            row["inventory_lines"] = inventory_lines
        else:
            row["inventory_id"] = None
            row["inventory_quantity"] = None
            row["inventory_on_sale_quantity"] = None
            row["inventory_match_count"] = 0
            row["inventory_locations_text"] = None
            row["inventory_mgmt_ids_text"] = None
            row["inventory_barcodes_text"] = None
            row["inventory_names_text"] = None
            row["inventory_lines"] = []


def _attach_description_mgmt_hints(items: list) -> None:
    """从 listing_description 解析明文/暗号管理番号，供列表与详情展示。"""
    if not items:
        return
    for row in items:
        desc = str(row.get("listing_description") or "").strip()
        if not desc:
            row["description_mgmt_ids"] = []
            row["description_mgmt_ids_text"] = None
            continue
        ids = parse_management_ids_from_description(desc)
        row["description_mgmt_ids"] = ids
        row["description_mgmt_ids_text"] = "、".join(str(i) for i in ids) if ids else None


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


class FetchOnSaleDetailsBatchRequest(PydanticModel):
    """同一账号下批量 items/get：在 run_meilu_serial_async 内串行执行，避免多请求并发抢占 WebDriver。"""
    item_ids: List[str]
    account_id: Optional[int] = None


_FETCH_DETAILS_BATCH_MAX = 200


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
    _attach_description_mgmt_hints(all_items)

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
    _attach_description_mgmt_hints(items)
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
    # 库存页二级列表：仅展示煤炉侧仍为「出售中」的行（同步后非出售中已从 inventory 解绑，此处作兜底过滤）
    items = [
        r
        for r in items
        if _is_active_on_sale(r.get("status"), int(r.get("is_delete") or 0))
    ]
    _attach_seller_name(items)
    _attach_inventory_by_item_id(items)
    _attach_description_mgmt_hints(items)
    return {"item_ids": ids, "total": len(items), "items": items}


@router.post("/sync")
async def sync_on_sale(data: SyncOnSaleRequest):
    """
    从煤炉拉取在售列表并同步本地：使用对应账号 Edge（meilu_{id}__auto）经 MITM 打开
    jp.mercari.com/mypage/listings，截获 api.mercari.jp/items/get_items 响应。
    在同一浏览器会话内，对本次**新增**的商品依次打开商品页截获 items/get，执行与「获取详情」相同的库存回写（可用 WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL=0 关闭）。
    新列表中不存在的本地记录不物理删除，而是标记 is_delete=1（软删除）。
    列表接口默认仅返回 is_delete=0 数据。须已启动 mitmdump（与出品/抓包共用）。
    """
    try:
        aid = resolve_meilu_account_id(data.account_id)
        result = await run_meilu_serial_async(
            queue_key_for_meilu_account(aid),
            lambda: sync_on_sale_items_from_mercari(account_id=aid),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步失败: {exc}") from exc
    return {"success": True, "data": result}


@router.post("/fetch-detail")
async def fetch_on_sale_item_detail(data: FetchOnSaleDetailRequest):
    """
    使用对应账号 Edge（MITM）打开 ``https://jp.mercari.com/item/m{item_id}``，
    截获 api.mercari.jp/items/get 响应；解析 data.description 中的末行暗号（-=~<>）、
    「管理ID / 管理番号 / バーコード」，
    匹配库存后写入 mercari_item_id、on_sale_quantity。须已启动 mitmdump。
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
        qk = queue_key_for_meilu_account(int(account_id))
        payload = await run_meilu_serial_async(
            qk,
            lambda: fetch_detail_and_sync_inventory(item_id, account_id=account_id),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取详情失败: {exc}") from exc

    return {"success": True, "data": payload}


@router.post("/fetch-details-batch")
async def fetch_on_sale_item_details_batch(data: FetchOnSaleDetailsBatchRequest):
    """
    对多个 item_id 依次执行 fetch_detail_and_sync_inventory，且整段只提交一次
    run_meilu_serial_async（与单条 fetch-detail、在售同步同一队列键 FIFO），避免多 HTTP
    并发在同一账号下抢占 Edge / MITM。
    """
    raw_ids = data.item_ids or []
    cleaned: List[str] = []
    seen: Set[str] = set()
    for x in raw_ids:
        t = str(x or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
    if not cleaned:
        raise HTTPException(status_code=400, detail="item_ids 不能为空")
    if len(cleaned) > _FETCH_DETAILS_BATCH_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多处理 {_FETCH_DETAILS_BATCH_MAX} 个商品 ID",
        )

    try:
        aid = resolve_meilu_account_id(data.account_id)
        qk = queue_key_for_meilu_account(int(aid))

        async def _run_batch() -> Dict[str, Any]:
            results: List[Dict[str, Any]] = []
            ok_synced = 0
            not_ok = 0
            for iid in cleaned:
                try:
                    payload = await fetch_detail_and_sync_inventory(iid, account_id=aid)
                    sync = payload.get("sync") if isinstance(payload.get("sync"), dict) else {}
                    if sync.get("updated"):
                        ok_synced += 1
                    else:
                        not_ok += 1
                    results.append({"item_id": iid, "sync": sync})
                except Exception as exc:
                    not_ok += 1
                    results.append({"item_id": iid, "sync": None, "error": str(exc)})
            return {
                "account_id": int(aid),
                "total": len(cleaned),
                "ok_synced": ok_synced,
                "not_ok": not_ok,
                "results": results,
            }

        out = await run_meilu_serial_async(qk, _run_batch)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"批量获取详情失败: {exc}") from exc

    return {"success": True, "data": out}
