# -*- coding: utf-8 -*-
"""库存管理共享辅助函数（被多个端点文件复用）。"""
import json
from typing import List
from ....db_manage.database import DatabaseManager

db = DatabaseManager()

MAX_INVENTORY_IMAGES = 20


INVENTORY_COLUMNS = [
    "id",
    "name",
    "barcode",
    "sku",
    "category_id",
    "product_type_id",
    "owner_user_id",
    "price",
    "quantity",
    "mercari_item_id",
    "on_sale_quantity",
    "pending_outbound_qty",
    "auto_listing_enabled",
    "is_delete",
    "is_combined",
    "combined_items",
    "description",
    "listing_title",
    "listing_body",
    "listing_status",
    "listing_account_id",
    "shipping_payer",
    "shipping_method",
    "shipping_from_area_id",
    "shipping_days",
    "sale_type",
    "auction_duration",
    "image",
    "image_front",
    "image_back",
    "images_json",
    "created_at",
    "warehouse_id",
]


def _row_to_inventory_detail(row: tuple) -> dict:
    keys = INVENTORY_COLUMNS + [
        "category_name",
        "warehouse_name",
        "inv_wh_name",
        "inv_shelf_name",
        "inv_shelf_code",
        "product_type_name",
        "owner_user_name",
    ]
    return dict(zip(keys, row))


def _inventory_paths_from_parsed_row(row_dict: dict) -> List[str]:
    """从行字典解析图片路径列表（优先 images_json，否则 image_front / image / image_back）。"""
    raw = row_dict.get("images_json")
    if raw and str(raw).strip():
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                out: List[str] = []
                for x in data:
                    if x is None:
                        continue
                    s = str(x).strip()
                    if s:
                        out.append(s)
                if out:
                    return out[:MAX_INVENTORY_IMAGES]
        except Exception:
            pass
    out: List[str] = []
    front = (row_dict.get("image_front") or row_dict.get("image") or "").strip()
    if front:
        out.append(front)
    back = (row_dict.get("image_back") or "").strip()
    if back:
        out.append(back)
    return out


def _enrich_inventory_api_dict(d: dict) -> dict:
    d["images"] = _inventory_paths_from_parsed_row(d)
    d.pop("images_json", None)
    return d


def _legacy_paths_from_db_columns(front, legacy_image, back, images_json_raw) -> List[str]:
    return _inventory_paths_from_parsed_row(
        {
            "image_front": front,
            "image": legacy_image,
            "image_back": back,
            "images_json": images_json_raw,
        }
    )


def _query_inventory_with_joins(where_sql: str = "", params: tuple = ()) -> list[dict]:
    from ....db_manage.models.warehouse import WarehouseModel

    select_cols = ", ".join([f"p.[{c}]" for c in INVENTORY_COLUMNS])
    wh_l = WarehouseModel.sql_display_label("w")
    wh_store = "COALESCE(NULLIF(TRIM(w.warehouse), ''), '默认仓库')"
    sql = f"""
        SELECT {select_cols}, c.name AS category_name, {wh_l} AS warehouse_name,
               {wh_store} AS inv_wh_name,
               NULLIF(TRIM(w.shelf_name), '') AS inv_shelf_name,
               w.name AS inv_shelf_code,
               ptcm.product_type AS product_type_name,
               COALESCE(u.display_name, u.username) AS owner_user_name
        FROM [inventory] p
        LEFT JOIN [categories] c ON c.id = p.category_id
        LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
        LEFT JOIN [product_type_category_mappings] ptcm
               ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        LEFT JOIN [users] u ON u.id = p.owner_user_id
        WHERE COALESCE(p.is_delete, 0) = 0 {where_sql}
    """
    rows = db.execute_query(sql, tuple(params))
    items = [_enrich_inventory_api_dict(_row_to_inventory_detail(r)) for r in rows]
    from ....use_mercari.on_sale_items_sync import enrich_inventory_rows_on_sale_quantity

    enrich_inventory_rows_on_sale_quantity(items)
    return items


def _inventory_exists(pid: int) -> bool:
    return bool(db.execute_query(
        "SELECT 1 FROM [inventory] WHERE id = ? AND COALESCE(is_delete, 0) = 0 LIMIT 1",
        (pid,),
    ))


def _warehouse_exists(wid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [warehouses] WHERE id = ? LIMIT 1", (wid,)))


def _user_exists(uid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [users] WHERE id = ? LIMIT 1", (uid,)))


def _sql_inventory_has_image_condition() -> str:
    """与 _inventory_paths_from_parsed_row 一致：任一有效图片路径即视为有图。"""
    return """
        (
            COALESCE(TRIM(p.image_front), TRIM(p.image), '') != ''
            OR COALESCE(TRIM(p.image_back), '') != ''
            OR (
                p.images_json IS NOT NULL
                AND TRIM(p.images_json) != ''
                AND TRIM(p.images_json) != '[]'
                AND json_valid(p.images_json) = 1
                AND EXISTS (
                    SELECT 1 FROM json_each(p.images_json) AS je
                    WHERE TRIM(COALESCE(je.value, '')) != ''
                )
            )
        )
    """
