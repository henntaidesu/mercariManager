# -*- coding: utf-8 -*-
"""
待办事项查询：分页 + 多条件过滤；联表 mercari_accounts 取 account_name 用于前端显示。
"""

import json
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager


_LIST_COLS = (
    "id",
    "account_id",
    "uuid",
    "kind",
    "title",
    "message",
    "photo_url",
    "photo_type",
    "status",
    "args_json",
    "intent_json",
    "item_id",
    "item_name",
    "sender_id",
    "mercari_created",
    "mercari_updated",
    "is_delete",
    "synced_at",
    "qr_image_path",
    "awaiting_feedback",
    "shipping_duration",
)


def list_todos(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    分页列出本地 ``todo_items``，附 ``account_name``。

    - ``include_deleted=False``（默认）只显示未完成（``is_delete=0``）
    - ``keyword`` 匹配 title / message / item_id / item_name
    """
    db = DatabaseManager()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    where = ["1=1"]
    params: List[Any] = []
    if not include_deleted:
        where.append("COALESCE(t.[is_delete], 0) = 0")
    if account_id is not None:
        where.append("t.[account_id] = ?")
        params.append(int(account_id))
    if kind:
        where.append("t.[kind] = ?")
        params.append(str(kind).strip())
    if keyword:
        kw = f"%{str(keyword).strip()}%"
        where.append(
            "(IFNULL(t.[title], '') LIKE ? "
            "OR IFNULL(t.[message], '') LIKE ? "
            "OR IFNULL(t.[item_id], '') LIKE ? "
            "OR IFNULL(t.[item_name], '') LIKE ?)"
        )
        params.extend([kw, kw, kw, kw])

    where_sql = " AND ".join(where)
    total = db.execute_query(
        f"SELECT COUNT(*) FROM [todo_items] t WHERE {where_sql}",
        tuple(params),
    )[0][0]

    sel_cols = ", ".join(f"t.[{c}]" for c in _LIST_COLS) + ", a.[account_name] AS account_name"
    offset = (page - 1) * page_size
    rows = db.execute_query(
        f"""
        SELECT {sel_cols}
        FROM [todo_items] t
        LEFT JOIN [mercari_accounts] a ON a.[id] = t.[account_id]
        WHERE {where_sql}
        ORDER BY t.[id] ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [page_size, offset]),
    )
    keys = list(_LIST_COLS) + ["account_name"]
    items = [dict(zip(keys, row)) for row in rows]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def _combined_component_locations(db: DatabaseManager, combined_items_raw: Any) -> List[Dict[str, Any]]:
    """解析组合商品的 ``combined_items``，返回每个来源商品的名称、数量与仓库位置。

    保持 ``combined_items`` 中的原始顺序，同一来源出现多次时合并数量。
    """
    if not combined_items_raw:
        return []
    try:
        parsed = json.loads(combined_items_raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []

    qty_by_id: Dict[int, int] = {}
    order: List[int] = []
    for it in parsed:
        if not isinstance(it, dict):
            continue
        try:
            cid = int(it.get("inventory_id"))
            qty = int(it.get("quantity"))
        except (TypeError, ValueError):
            continue
        if cid > 0 and qty > 0:
            if cid not in qty_by_id:
                order.append(cid)
            qty_by_id[cid] = qty_by_id.get(cid, 0) + qty
    if not order:
        return []

    placeholders = ",".join("?" for _ in order)
    rows = db.execute_query(
        f"""
        SELECT c.id, c.name,
               NULLIF(TRIM(w.warehouse), '') AS warehouse_name,
               NULLIF(TRIM(w.shelf_name), '') AS shelf_name,
               NULLIF(TRIM(w.name), '') AS shelf_code
        FROM [inventory] c
        LEFT JOIN [warehouses] w ON w.id = c.warehouse_id
        WHERE c.id IN ({placeholders})
        """,
        tuple(order),
    )
    by_id = {int(r[0]): r for r in rows}

    out: List[Dict[str, Any]] = []
    for cid in order:
        r = by_id.get(cid)
        out.append({
            "id": cid,
            "name": r[1] if r is not None else None,
            "quantity": qty_by_id[cid],
            "warehouse_name": r[2] if r is not None else None,
            "shelf_name": r[3] if r is not None else None,
            "shelf_code": r[4] if r is not None else None,
        })
    return out


def match_inventory_for_item(item_id: str) -> Dict[str, Any]:
    """
    「発送をしてください」处理：按煤炉商品 ID 反查本地库存与关联订单。

    链路：todo.item_id 即订单号（orders.order_no == item_id）
          → order_outbound_lines.inventory_id（库存ID，组合购买可多条）
          → inventory 本地图片。

    返回该订单关联的每条库存的本地图片路径列表（images_json / image_front /
    image / image_back），供前端在处理弹窗中展示全部图片。
    """
    from ...inventory.units.inventory_helpers import _inventory_paths_from_parsed_row

    iid = (item_id or "").strip()
    if not iid:
        return {"item_id": "", "inventory": [], "order_nos": []}

    db = DatabaseManager()
    # item_id 即订单号：取该订单出库明细关联的库存（去重，按明细排序）
    inv_rows = db.execute_query(
        """
        SELECT p.id, p.name, p.image, p.image_front, p.image_back, p.images_json,
               NULLIF(TRIM(w.warehouse), '') AS warehouse_name,
               NULLIF(TRIM(w.shelf_name), '') AS shelf_name,
               NULLIF(TRIM(w.name), '') AS shelf_code,
               ptcm.product_type AS product_type_name,
               COALESCE(p.is_combined, 0) AS is_combined,
               p.combined_items AS combined_items,
               MIN(l.sort_index) AS sort_index, MIN(l.id) AS line_id
        FROM [order_outbound_lines] l
        INNER JOIN [inventory] p ON p.id = l.inventory_id
        LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
        LEFT JOIN [product_type_category_mappings] ptcm
               ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        WHERE l.order_no = ?
          AND l.inventory_id IS NOT NULL
          AND COALESCE(p.is_delete, 0) = 0
        GROUP BY p.id
        ORDER BY sort_index ASC, line_id ASC
        """,
        (iid,),
    )
    keys = [
        "id", "name", "image", "image_front", "image_back", "images_json",
        "warehouse_name", "shelf_name", "shelf_code", "product_type_name",
        "is_combined", "combined_items",
        "sort_index", "line_id",
    ]
    inventory: List[Dict[str, Any]] = []
    for row in inv_rows:
        d = dict(zip(keys, row))
        is_combined = bool(int(d.get("is_combined") or 0))
        # 组合（捆绑）库存：展开其来源商品，逐个回显仓库位置（组合本身的位置往往为空）
        components = (
            _combined_component_locations(db, d.get("combined_items"))
            if is_combined
            else []
        )
        inventory.append({
            "id": d["id"],
            "name": d["name"],
            "product_type_name": d["product_type_name"],
            "images": _inventory_paths_from_parsed_row(d),
            "warehouse_name": d["warehouse_name"],
            "shelf_name": d["shelf_name"],
            "shelf_code": d["shelf_code"],
            "is_combined": is_combined,
            "components": components,
        })

    # 订单号即 item_id：仅当库中确有该订单时回显
    order_nos: List[str] = []
    has_order = db.execute_query(
        "SELECT 1 FROM [orders] WHERE order_no = ? LIMIT 1",
        (iid,),
    )
    if has_order:
        order_nos = [iid]

    return {"item_id": iid, "inventory": inventory, "order_nos": order_nos}


def list_kinds() -> List[str]:
    """返回所有出现过的 kind（前端做下拉用，含已删行也算）。"""
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT DISTINCT [kind] FROM [todo_items] "
        "WHERE [kind] IS NOT NULL AND TRIM([kind]) != '' ORDER BY [kind] ASC"
    )
    return [r[0] for r in rows if r and r[0]]
