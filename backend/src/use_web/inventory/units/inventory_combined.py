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


def _validate_combined_sources(items: list[dict]) -> None:
    """校验组合来源商品：必须存在且自身不是组合商品（组合商品不再扣减来源库存，仅做合法性校验）。"""
    if not items:
        return
    ids = [int(item["inventory_id"]) for item in items]
    placeholders = ",".join("?" for _ in ids)
    rows = db.execute_query(
        f"SELECT id, is_combined FROM [inventory] WHERE id IN ({placeholders}) AND COALESCE(is_delete, 0) = 0",
        tuple(ids),
    )
    found = {int(r[0]): int(r[1] or 0) for r in rows}
    if len(found) != len(set(ids)):
        raise HTTPException(status_code=400, detail="组合商品包含不存在的商品")
    for source_id, is_comb in found.items():
        if is_comb:
            raise HTTPException(status_code=400, detail="组合商品不能再次作为组合来源")


def create_combined_inventory(data: CombinedInventoryCreate, _claims: dict = Depends(require_auth)):
    """将一件或多件库存商品组合成一个新的库存商品（组合商品不扣减来源库存，来源被「拉走」的件数仅作展示与可上架扣减）。"""
    combo_quantity = int(data.quantity or 0)
    if combo_quantity <= 0:
        raise HTTPException(status_code=400, detail="组合商品库存数量必须大于0")
    if data.warehouse_id is not None and not _warehouse_exists(data.warehouse_id):
        raise HTTPException(status_code=400, detail="所属货架不存在")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")

    items = _normalize_combined_components(data.components)
    _validate_combined_sources(items)
    paths = _resolve_paths_for_combined_create(data)
    img_cols = _sync_image_columns_from_paths(paths)
    barcode = f"COMBO-{int(time.time() * 1000)}"
    name = (data.name or "").strip() or "组合商品"
    combined_items_json = json.dumps(items, ensure_ascii=False, separators=(",", ":"))

    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
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

    # 组合商品新增后，来源商品被「拉走」的件数变化，重算其可上架（库存不变）。
    from ....use_mercari.inventory_counters import recompute_listable_quantity
    recompute_listable_quantity([int(item["inventory_id"]) for item in items])

    from ..image_search import enqueue_inventory as _enqueue_image_index
    _enqueue_image_index(new_id)

    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return inventory_items[0] if inventory_items else {"id": new_id}


def remove_combined_component(pid: int, component_id: int, _claims: dict = Depends(require_auth)):
    """从组合商品的组成明细中删除一个来源商品。

    来源被「拉走」的件数（组合预留）由 combined_items 派生，移除明细后该来源的「组合数量」
    随之减少；据此重算其可上架（库存不变）。至少需保留一件来源商品，整组清空请删除该组合商品。
    """
    rows = db.execute_query(
        "SELECT is_combined, combined_items FROM [inventory] WHERE id = ? AND COALESCE(is_delete, 0) = 0 LIMIT 1",
        (pid,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="组合商品不存在")
    if not int(rows[0][0] or 0):
        raise HTTPException(status_code=400, detail="该商品不是组合商品")

    items = _parse_combined_items(rows[0][1])
    if not any(int(it["inventory_id"]) == int(component_id) for it in items):
        raise HTTPException(status_code=404, detail="组合明细中不存在该商品")

    remaining = [it for it in items if int(it["inventory_id"]) != int(component_id)]
    if not remaining:
        raise HTTPException(status_code=400, detail="组合商品至少需保留一件来源商品，请直接删除该组合商品")

    new_json = json.dumps(remaining, ensure_ascii=False, separators=(",", ":"))
    db.execute_update("UPDATE [inventory] SET combined_items = ? WHERE id = ?", (new_json, pid))

    # 该来源被「拉走」的件数减少，重算其可上架（库存不变）。
    from ....use_mercari.inventory_counters import recompute_listable_quantity
    recompute_listable_quantity([int(component_id)])

    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    return inventory_items[0] if inventory_items else {"id": pid}
