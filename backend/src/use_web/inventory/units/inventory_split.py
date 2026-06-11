# -*- coding: utf-8 -*-
"""库存拆分端点：将一个商品拆分出一个新的库存条目（新管理番号），可指定不同的商品归属。"""
import os
import time
import shutil
import uuid
from fastapi import HTTPException, Depends

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ...image_storage import get_image_root

from .inventory_helpers import (
    _query_inventory_with_joins,
    _inventory_exists,
    _user_exists,
    _legacy_paths_from_db_columns,
)
from .inventory_images import _sync_image_columns_from_paths
from .inventory_models import InventorySplitRequest

db = DatabaseManager()


def _duplicate_image_file(path: str) -> str:
    """物理复制一张 /imges/xxx 图片，返回新路径，避免拆分后两条记录共享同一文件导致删除冲突。"""
    if not path or not isinstance(path, str) or not path.startswith("/imges/"):
        return path
    filename = path.split("/imges/", 1)[1].strip("/")
    if not filename:
        return path
    src_abs = os.path.join(get_image_root(), filename)
    if not os.path.exists(src_abs):
        return path
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    new_name = f"inv_split_{uuid.uuid4().hex}.{ext}"
    dst_abs = os.path.join(get_image_root(), new_name)
    try:
        shutil.copyfile(src_abs, dst_abs)
    except Exception:
        return path
    return f"/imges/{new_name}"


def split_inventory(pid: int, data: InventorySplitRequest, _claims: dict = Depends(require_auth)):
    """将商品按指定数量拆分出一条新库存（新管理番号），并可同时切换商品归属。"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    split_qty = int(data.split_quantity or 0)
    if split_qty < 0:
        raise HTTPException(status_code=400, detail="拆分数量不能小于0")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")

    rows = db.execute_query(
        """
        SELECT name, barcode, category_id, product_type_id, owner_user_id, warehouse_id,
               price, quantity, description, listing_title, listing_body,
               image, image_front, image_back, images_json, is_combined
        FROM [inventory] WHERE id = ? LIMIT 1
        """,
        (pid,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="商品不存在")
    src = rows[0]
    src_quantity = int(src[7] or 0)
    is_combined = int(src[15] or 0)

    if is_combined:
        raise HTTPException(status_code=400, detail="组合商品不能拆分")
    if split_qty > src_quantity:
        raise HTTPException(
            status_code=400,
            detail=f"拆分数量不能超过当前库存（{src_quantity}）",
        )

    new_owner = data.owner_user_id if data.owner_user_id is not None else src[4]
    new_barcode = f"SPLIT-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"

    src_paths = _legacy_paths_from_db_columns(src[12], src[11], src[13], src[14])
    new_paths = [_duplicate_image_file(p) for p in src_paths]
    img_cols = _sync_image_columns_from_paths(new_paths)

    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            if split_qty > 0:
                cur.execute(
                    "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) - ? WHERE id = ?",
                    (split_qty, pid),
                )
            cur.execute(
                """
                INSERT INTO [inventory] (
                    name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                    mercari_item_id, on_sale_quantity, pending_outbound_qty,
                    description, listing_title, listing_body, image, image_front, image_back, images_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src[0], new_barcode, src[2], src[3], new_owner, src[5], src[6], split_qty,
                    None, 0, 0,
                    src[8], src[9], src[10],
                    img_cols["image"], img_cols["image_front"], img_cols["image_back"], img_cols["images_json"],
                ),
            )
            new_id = cur.lastrowid
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="拆分失败，请稍后重试")

    from ..image_search import enqueue_inventory as _enqueue_image_index
    _enqueue_image_index(new_id)

    items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return items[0] if items else {"id": new_id}
