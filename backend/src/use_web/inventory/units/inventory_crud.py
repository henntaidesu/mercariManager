# -*- coding: utf-8 -*-
"""库存创建/更新/删除端点。"""
from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ...image_storage import delete_image_file

from .inventory_helpers import (
    _query_inventory_with_joins,
    _inventory_exists,
    _warehouse_exists,
    _user_exists,
    _legacy_paths_from_db_columns,
)
from .inventory_images import (
    _normalize_images_input_list,
    _convert_image_list_to_paths,
    _sync_image_columns_from_paths,
    _delete_paths_removed,
    _convert_image_payload,
    _resolve_paths_for_create,
)
from .inventory_combined import _parse_combined_items, _adjust_combined_source_stock
from .inventory_models import InventoryCreate, InventoryUpdate

db = DatabaseManager()


def create_inventory(data: InventoryCreate, _claims: dict = Depends(require_auth)):
    if not (data.barcode or "").strip():
        raise HTTPException(status_code=400, detail="条形码必填")
    if data.warehouse_id is not None and not _warehouse_exists(data.warehouse_id):
        raise HTTPException(status_code=400, detail="所属货架不存在")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")
    paths = _resolve_paths_for_create(data)
    img_cols = _sync_image_columns_from_paths(paths)
    try:
        new_id = db.execute_insert(
            """
            INSERT INTO [inventory] (
                name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                mercari_item_id, on_sale_quantity, pending_outbound_qty, auto_listing_enabled,
                description, listing_title, listing_body,
                listing_status, listing_account_id, shipping_payer, shipping_method,
                shipping_from_area_id, shipping_days, sale_type, auction_duration,
                image, image_front, image_back, images_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.name,
                data.barcode.strip(),
                data.category_id,
                data.product_type_id,
                data.owner_user_id,
                data.warehouse_id,
                data.price,
                data.quantity,
                (data.mercari_item_id or "").strip() or None,
                int(data.on_sale_quantity) if data.on_sale_quantity is not None else 0,
                0,
                1 if int(data.auto_listing_enabled or 0) == 1 else 0,
                data.description,
                data.listing_title,
                data.listing_body,
                data.listing_status,
                data.listing_account_id,
                data.shipping_payer,
                data.shipping_method,
                data.shipping_from_area_id,
                data.shipping_days,
                data.sale_type,
                data.auction_duration,
                img_cols["image"],
                img_cols["image_front"],
                img_cols["image_back"],
                img_cols["images_json"],
            ),
        )
    except Exception as exc:
        err = str(exc).lower()
        if "unique" in err and "barcode" in err:
            raise HTTPException(status_code=400, detail="保存失败，条形码可能重复")
        raise HTTPException(status_code=400, detail="保存失败，请检查填写内容后重试")
    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return inventory_items[0] if inventory_items else {"id": new_id}


def update_inventory(pid: int, data: InventoryUpdate, _claims: dict = Depends(require_auth)):
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    update_data = data.model_dump(exclude_unset=True)
    if 'barcode' in update_data and not (update_data.get('barcode') or '').strip():
        raise HTTPException(status_code=400, detail="条形码不能为空")
    if 'barcode' in update_data:
        update_data['barcode'] = update_data['barcode'].strip()
    existing = db.execute_query(
        """
        SELECT image, image_front, image_back, images_json, warehouse_id, owner_user_id,
               is_combined, combined_items, quantity
        FROM [inventory] WHERE id = ? LIMIT 1
        """,
        (pid,),
    )
    old_image = existing[0][0] if existing else None
    old_front = existing[0][1] if existing else None
    old_back = existing[0][2] if existing else None
    old_images_json = existing[0][3] if existing else None
    old_warehouse_id = existing[0][4] if existing else None
    old_owner_user_id = existing[0][5] if existing else None
    old_is_combined = int(existing[0][6] or 0) if existing else 0
    old_combined_items = existing[0][7] if existing else None
    old_quantity = int(existing[0][8] or 0) if existing else 0

    old_paths = _legacy_paths_from_db_columns(old_front, old_image, old_back, old_images_json)

    if 'images' in update_data:
        update_data.pop('image_front', None)
        update_data.pop('image_back', None)
        update_data.pop('image', None)
        raw_images = update_data.pop('images')
        normalized = _normalize_images_input_list(raw_images, "images")
        if normalized is None:
            normalized = []
        new_paths = _convert_image_list_to_paths(normalized)
        _delete_paths_removed(old_paths, new_paths)
        update_data.update(_sync_image_columns_from_paths(new_paths))
    else:
        if 'image_front' in update_data:
            new_front = _convert_image_payload(update_data.get('image_front'), "inventory_front")
            update_data['image_front'] = new_front
            update_data['image'] = new_front
            if old_front and old_front != new_front:
                delete_image_file(old_front)
        if 'image_back' in update_data:
            new_back = _convert_image_payload(update_data.get('image_back'), "inventory_back")
            update_data['image_back'] = new_back
            if old_back and old_back != new_back:
                delete_image_file(old_back)
    final_warehouse_id = update_data['warehouse_id'] if 'warehouse_id' in update_data else old_warehouse_id
    if 'warehouse_id' in update_data:
        if final_warehouse_id is not None and not _warehouse_exists(final_warehouse_id):
            raise HTTPException(status_code=400, detail="所属货架不存在")
    if 'owner_user_id' in update_data:
        new_owner_user_id = update_data['owner_user_id']
        if new_owner_user_id is not None and not _user_exists(new_owner_user_id):
            raise HTTPException(status_code=400, detail="商品归属用户不存在")
    if "auto_listing_enabled" in update_data:
        update_data["auto_listing_enabled"] = 1 if int(update_data.get("auto_listing_enabled") or 0) == 1 else 0
    allowed_fields = {
        "name", "barcode", "category_id", "product_type_id", "owner_user_id", "warehouse_id", "price",
        "quantity",
        "mercari_item_id", "on_sale_quantity", "auto_listing_enabled",
        "description", "listing_title", "listing_body",
        "listing_status", "listing_account_id", "shipping_payer", "shipping_method",
        "shipping_from_area_id", "shipping_days", "sale_type", "auction_duration",
        "image", "image_front", "image_back", "images_json",
    }
    update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
    if update_data:
        set_sql = ", ".join([f"[{k}] = ?" for k in update_data.keys()])
        params = tuple(update_data.values()) + (pid,)
        try:
            if old_is_combined and "quantity" in update_data:
                new_quantity = int(update_data.get("quantity") or 0)
                if new_quantity < 0:
                    raise HTTPException(status_code=400, detail="库存数量不能小于0")
                delta = new_quantity - old_quantity
                with db.get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("BEGIN IMMEDIATE")
                    _adjust_combined_source_stock(cur, _parse_combined_items(old_combined_items), delta)
                    cur.execute(f"UPDATE [inventory] SET {set_sql} WHERE id = ?", params)
                    conn.commit()
            else:
                db.execute_update(f"UPDATE [inventory] SET {set_sql} WHERE id = ?", params)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="更新失败，条形码可能重复")
    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    if not inventory_items:
        raise HTTPException(status_code=400, detail="更新失败，条形码可能重复")
    return inventory_items[0]


def delete_inventory(pid: int):
    """假删除：仅置 is_delete=1，保留图片与数据，可通过数据库手动恢复（SET is_delete=0）。"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    db.execute_update(
        "UPDATE [inventory] SET is_delete = 1 WHERE id = ? AND COALESCE(is_delete, 0) = 0",
        (pid,),
    )
    return {"message": "删除成功"}
