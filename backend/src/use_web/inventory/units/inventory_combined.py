# -*- coding: utf-8 -*-
"""组合（捆绑）商品相关辅助函数与端点。"""
import json
import time
from typing import Optional
from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager

from .inventory_helpers import (
    _query_inventory_with_joins,
    _warehouse_exists,
    _user_exists,
)
from .inventory_images import (
    _resolve_paths_for_combined_create,
    _sync_image_columns_from_paths,
)
from .inventory_models import CombinedInventoryComponent, CombinedInventoryCreate

db = DatabaseManager()


def _parse_combined_items(raw: Optional[str]) -> list[dict]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    items = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            inventory_id = int(item.get("inventory_id"))
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError):
            continue
        if inventory_id > 0 and quantity > 0:
            items.append({"inventory_id": inventory_id, "quantity": quantity})
    return items


def _normalize_combined_components(components: list[CombinedInventoryComponent]) -> list[dict]:
    grouped: dict[int, int] = {}
    for comp in components or []:
        try:
            inventory_id = int(comp.inventory_id)
            quantity = int(comp.quantity)
        except (TypeError, ValueError):
            continue
        if inventory_id <= 0 or quantity <= 0:
            raise HTTPException(status_code=400, detail="组合商品的商品数量必须大于0")
        grouped[inventory_id] = grouped.get(inventory_id, 0) + quantity
    items = [{"inventory_id": iid, "quantity": qty} for iid, qty in grouped.items()]
    if not items:
        raise HTTPException(status_code=400, detail="组合商品至少需要一件来源商品")
    return items


def _adjust_combined_source_stock(cur, items: list[dict], combo_delta: int) -> None:
    """combo_delta > 0 消耗原商品；combo_delta < 0 回补原商品。"""
    if combo_delta == 0 or not items:
        return
    ids = [int(item["inventory_id"]) for item in items]
    placeholders = ",".join("?" for _ in ids)
    cur.execute(
        f"SELECT id, quantity, is_combined FROM [inventory] WHERE id IN ({placeholders})",
        tuple(ids),
    )
    rows = {int(r[0]): {"quantity": int(r[1] or 0), "is_combined": int(r[2] or 0)} for r in cur.fetchall()}
    if len(rows) != len(ids):
        raise HTTPException(status_code=400, detail="组合商品包含不存在的商品")
    for item in items:
        source_id = int(item["inventory_id"])
        per_combo_qty = int(item["quantity"])
        row = rows[source_id]
        if row["is_combined"]:
            raise HTTPException(status_code=400, detail="组合商品不能再次作为组合来源")
        change = per_combo_qty * abs(combo_delta)
        if combo_delta > 0 and row["quantity"] < change:
            raise HTTPException(status_code=400, detail=f"管理番号 {source_id} 库存不足，当前库存：{row['quantity']}")
        op = "-" if combo_delta > 0 else "+"
        cur.execute(
            f"UPDATE [inventory] SET quantity = COALESCE(quantity, 0) {op} ? WHERE id = ?",
            (change, source_id),
        )
        # 来源库存数量变化后，同步重算其「可上架」= 库存 - 在售 - 待出
        cur.execute(
            "UPDATE [inventory] SET [listable_quantity] = "
            "MAX(0, COALESCE([quantity],0) - COALESCE([on_sale_quantity],0) - COALESCE([pending_outbound_qty],0)) "
            "WHERE id = ?",
            (source_id,),
        )


def create_combined_inventory(data: CombinedInventoryCreate, _claims: dict = Depends(require_auth)):
    """将一件或多件库存商品组合成一个新的库存商品，并扣减来源库存（单 SKU 时通过 components 数量表示每套几件）。"""
    combo_quantity = int(data.quantity or 0)
    if combo_quantity <= 0:
        raise HTTPException(status_code=400, detail="组合商品库存数量必须大于0")
    if data.warehouse_id is not None and not _warehouse_exists(data.warehouse_id):
        raise HTTPException(status_code=400, detail="所属货架不存在")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")

    items = _normalize_combined_components(data.components)
    paths = _resolve_paths_for_combined_create(data)
    img_cols = _sync_image_columns_from_paths(paths)
    barcode = f"COMBO-{int(time.time() * 1000)}"
    name = (data.name or "").strip() or "组合商品"
    combined_items_json = json.dumps(items, ensure_ascii=False, separators=(",", ":"))

    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            _adjust_combined_source_stock(cur, items, combo_quantity)
            cur.execute(
                """
                INSERT INTO [inventory] (
                    name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                    mercari_item_id, on_sale_quantity, pending_outbound_qty, is_combined, combined_items,
                    description, listing_title, listing_body, image, image_front, image_back, images_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    barcode,
                    data.category_id,
                    data.product_type_id,
                    data.owner_user_id,
                    data.warehouse_id,
                    data.price,
                    combo_quantity,
                    None,
                    0,
                    0,
                    1,
                    combined_items_json,
                    data.description,
                    data.listing_title,
                    data.listing_body,
                    img_cols["image"],
                    img_cols["image_front"],
                    img_cols["image_back"],
                    img_cols["images_json"],
                ),
            )
            new_id = cur.lastrowid
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="组合商品创建失败")

    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return inventory_items[0] if inventory_items else {"id": new_id}
