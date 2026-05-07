# -*- coding: utf-8 -*-
import io
import os
import time
import base64
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi import Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel as PydanticModel, field_validator
from typing import Optional
from PIL import Image, ImageOps
from ..auth import require_auth
from ..db_manage.database import DatabaseManager
from ..image_storage import is_base64_image, save_base64_image, delete_image_file, get_image_root

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
# 公开路由：缩略图等无需登录即可访问（图片本身已通过静态文件公开）
public_router = APIRouter(prefix="/api/inventory", tags=["inventory-public"])
db = DatabaseManager()

PRODUCT_COLUMNS = [
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
    "description",
    "listing_title",
    "listing_body",
    "image",
    "image_front",
    "image_back",
    "created_at",
    "warehouse_id",
]


class StockInRequest(PydanticModel):
    warehouse_id: Optional[int] = None   # 不传则只更新库存，不写事务记录
    quantity: int = 1
    remark: Optional[str] = None


class ProductCreate(PydanticModel):
    name: Optional[str] = None
    barcode: str
    category_id: Optional[int] = None
    product_type_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    price: int = 0
    quantity: Optional[int] = 1
    description: Optional[str] = None
    listing_title: Optional[str] = None
    listing_body: Optional[str] = None
    mercari_item_id: Optional[str] = None
    on_sale_quantity: Optional[int] = None
    image_front: Optional[str] = None
    image_back: Optional[str] = None

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0


class ProductUpdate(PydanticModel):
    name: Optional[str] = None
    barcode: Optional[str] = None
    category_id: Optional[int] = None
    product_type_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    price: Optional[int] = None
    quantity: Optional[int] = None
    description: Optional[str] = None
    listing_title: Optional[str] = None
    listing_body: Optional[str] = None
    mercari_item_id: Optional[str] = None
    on_sale_quantity: Optional[int] = None
    image_front: Optional[str] = None
    image_back: Optional[str] = None

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int_opt(cls, v):
        if v is None or v == '':
            return None
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None


def _row_to_product_detail(row: tuple) -> dict:
    keys = PRODUCT_COLUMNS + [
        "category_name",
        "warehouse_name",
        "inv_wh_name",
        "inv_shelf_name",
        "inv_shelf_code",
        "product_type_name",
        "owner_user_name",
    ]
    return dict(zip(keys, row))


def _query_product_with_joins(where_sql: str = "", params: tuple = ()) -> list[dict]:
    from ..db_manage.models.warehouse import WarehouseModel

    select_cols = ", ".join([f"p.[{c}]" for c in PRODUCT_COLUMNS])
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
        WHERE 1=1 {where_sql}
    """
    rows = db.execute_query(sql, tuple(params))
    return [_row_to_product_detail(r) for r in rows]


def _product_exists(pid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [inventory] WHERE id = ? LIMIT 1", (pid,)))


def _warehouse_exists(wid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [warehouses] WHERE id = ? LIMIT 1", (wid,)))


def _user_exists(uid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [users] WHERE id = ? LIMIT 1", (uid,)))


def _is_system_admin(claims: dict) -> bool:
    username = (claims.get("username") or "").strip()
    if username == "admin":
        return True
    rows = db.execute_query(
        "SELECT 1 FROM [users] WHERE username = ? AND display_name = ? LIMIT 1",
        (username, "系统管理员"),
    )
    return bool(rows)


def _convert_image_payload(image_value: Optional[str], prefix: str) -> Optional[str]:
    if image_value is None:
        return None
    val = image_value.strip() if isinstance(image_value, str) else image_value
    if not val:
        return None
    if is_base64_image(val):
        try:
            return save_base64_image(val, prefix=prefix)
        except Exception:
            raise HTTPException(status_code=400, detail="图片格式无效或保存失败")
    return val


def _to_dhash(image: Image.Image) -> int:
    """计算 64bit dHash，用于快速近似匹配"""
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    value = 0
    bit = 0
    for y in range(8):
        row_offset = y * 9
        for x in range(8):
            left = pixels[row_offset + x]
            right = pixels[row_offset + x + 1]
            if left > right:
                value |= (1 << bit)
            bit += 1
    return value


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _load_image_for_match(image_value: Optional[str]) -> Optional[Image.Image]:
    if not image_value or not isinstance(image_value, str):
        return None
    val = image_value.strip()
    if not val:
        return None
    try:
        if val.startswith("data:image/"):
            b64 = val.split(",", 1)[1] if "," in val else val
            return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        if val.startswith("/imges/"):
            abs_path = os.path.join(get_image_root(), val.split("/imges/", 1)[1].strip("/"))
            if os.path.exists(abs_path):
                return Image.open(abs_path).convert("RGB")
    except Exception:
        return None
    return None


@public_router.get("/image-thumb")
def get_image_thumb(path: str, size: int = 300):
    """
    按需生成缩略图并缓存到磁盘。
    - path: /imges/xxx.jpg 格式
    - size: 最长边像素（默认 300，列表小图用 200 即可）
    """
    clean = (path or "").strip()
    if not clean.startswith("/imges/") or ".." in clean:
        raise HTTPException(status_code=400, detail="无效路径")
    size = max(50, min(size, 1200))

    filename = clean.split("/imges/", 1)[1].strip("/")
    orig_abs = os.path.join(get_image_root(), filename)
    if not os.path.exists(orig_abs):
        raise HTTPException(status_code=404, detail="图片不存在")

    # 缩略图缓存目录
    thumb_dir = os.path.join(get_image_root(), "_thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    # 将路径分隔符统一替换，避免子目录名带入文件名
    safe_stem = stem.replace("/", "_").replace("\\", "_")
    thumb_filename = f"{safe_stem}_s{size}.jpg"
    thumb_abs = os.path.join(thumb_dir, thumb_filename)

    if not os.path.exists(thumb_abs):
        try:
            img = Image.open(orig_abs)
            # 先应用 EXIF 方向信息，避免手机竖拍图片在缩略图中出现旋转偏差
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > size:
                scale = size / max(w, h)
                img = img.resize(
                    (int(w * scale), int(h * scale)),
                    Image.Resampling.LANCZOS,
                )
            img.save(thumb_abs, "JPEG", quality=75, optimize=True)
        except Exception:
            # PIL 无法处理时直接返回原图
            return FileResponse(orig_abs)

    return FileResponse(thumb_abs, media_type="image/jpeg")


@router.get("")
def list_inventory(
    keyword: Optional[str] = None,
    category_id: Optional[int] = None,
    product_type_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    in_stock_only: bool = False,
):
    where_parts = []
    params = []
    if keyword:
        where_parts.append("AND p.name LIKE ?")
        params.append(f"%{keyword}%")
    if category_id:
        where_parts.append("AND p.category_id = ?")
        params.append(category_id)
    if product_type_id:
        where_parts.append("AND p.product_type_id = ?")
        params.append(product_type_id)
    if owner_user_id:
        where_parts.append("AND p.owner_user_id = ?")
        params.append(owner_user_id)
    if warehouse_id:
        where_parts.append("AND p.warehouse_id = ?")
        params.append(warehouse_id)
    if in_stock_only:
        where_parts.append("AND COALESCE(p.quantity, 0) > 0")
    where_sql = " " + " ".join(where_parts) + " ORDER BY p.id DESC"
    return _query_product_with_joins(where_sql, tuple(params))


@router.get("/barcode/{barcode}")
def find_by_barcode(barcode: str):
    """根据条形码精确查找商品（用于连续扫码流程）"""
    inventory_items = _query_product_with_joins(" AND p.barcode = ? LIMIT 1", (barcode.strip(),))
    if not inventory_items:
        return {"found": False, "product": None}
    return {"found": True, "product": inventory_items[0]}


@router.post("/find-by-image")
async def find_by_image(file: UploadFile = File(...)):
    """根据上传的正面照片匹配最相近库存商品"""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片内容为空")
    try:
        query_img = Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="图片解析失败，请重试")

    query_hash = _to_dhash(query_img)
    rows = db.execute_query("SELECT id, image_front, image FROM [inventory]")
    best_id = None
    best_distance = 999

    for pid, image_front, image in rows:
        candidate_img = _load_image_for_match(image_front) or _load_image_for_match(image)
        if candidate_img is None:
            continue
        distance = _hamming_distance(query_hash, _to_dhash(candidate_img))
        if distance < best_distance:
            best_distance = distance
            best_id = pid

    if best_id is None:
        return {"found": False, "product": None, "distance": None}

    # 经验阈值：dHash 64bit，距离越小越像；>18 误匹配概率明显增高
    if best_distance > 18:
        return {"found": False, "product": None, "distance": best_distance}

    matched = _query_product_with_joins(" AND p.id = ? LIMIT 1", (best_id,))
    if not matched:
        return {"found": False, "product": None, "distance": best_distance}
    return {"found": True, "product": matched[0], "distance": best_distance}


@router.post("/{pid}/stock-in")
def stock_in_product(pid: int, data: StockInRequest):
    """连续扫码入库：库存 +N；若提供 warehouse_id 则同时写入事务记录"""
    if not _product_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="入库数量必须大于0")
    affected = db.execute_update(
        "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) + ? WHERE id = ?",
        (data.quantity, pid),
    )
    if affected <= 0:
        raise HTTPException(status_code=500, detail="库存更新失败")
    if data.warehouse_id:
        db.execute_insert(
            """
            INSERT INTO [transactions] (
                type, product_id, warehouse_id, quantity, remark, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "in",
                pid,
                data.warehouse_id,
                data.quantity,
                data.remark or "扫码快速入库",
                int(time.time()),
            ),
        )
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "product_id": pid}


@router.post("/{pid}/stock-out")
def stock_out_product(pid: int, data: StockInRequest):
    """连续扫码出库：库存 -N；若提供 warehouse_id 则同时写入事务记录"""
    if not _product_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="出库数量必须大于0")
    current_qty_row = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
    current_qty = (current_qty_row[0][0] if current_qty_row else 0) or 0
    if current_qty < data.quantity:
        raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
    affected = db.execute_update(
        "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) - ? WHERE id = ?",
        (data.quantity, pid),
    )
    if affected <= 0:
        raise HTTPException(status_code=500, detail="库存更新失败")
    if data.warehouse_id:
        db.execute_insert(
            """
            INSERT INTO [transactions] (
                type, product_id, warehouse_id, quantity, remark, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "out",
                pid,
                data.warehouse_id,
                data.quantity,
                data.remark or "扫码快速出库",
                int(time.time()),
            ),
        )
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "product_id": pid}


@router.get("/{pid}")
def get_product(pid: int):
    inventory_items = _query_product_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    if not inventory_items:
        raise HTTPException(status_code=404, detail="商品不存在")
    return inventory_items[0]


@router.post("")
def create_product(data: ProductCreate, claims: dict = Depends(require_auth)):
    if not (data.barcode or "").strip():
        raise HTTPException(status_code=400, detail="条形码必填")
    if data.warehouse_id is None:
        raise HTTPException(status_code=400, detail="所属仓库必填")
    if not _warehouse_exists(data.warehouse_id):
        raise HTTPException(status_code=400, detail="所属仓库不存在")
    if data.owner_user_id is not None and not _is_system_admin(claims):
        raise HTTPException(status_code=403, detail="仅系统管理员可修改商品归属")
    if data.owner_user_id is not None and not _user_exists(data.owner_user_id):
        raise HTTPException(status_code=400, detail="商品归属用户不存在")
    image_front_path = _convert_image_payload(data.image_front, "product_front")
    image_back_path = _convert_image_payload(data.image_back, "product_back")
    try:
        new_id = db.execute_insert(
            """
            INSERT INTO [inventory] (
                name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                mercari_item_id, on_sale_quantity, pending_outbound_qty,
                description, listing_title, listing_body, image, image_front, image_back
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data.description,
                data.listing_title,
                data.listing_body,
                image_front_path,
                image_front_path,
                image_back_path,
            ),
        )
    except Exception:
        raise HTTPException(status_code=400, detail="保存失败，条形码可能重复")
    inventory_items = _query_product_with_joins(" AND p.id = ? LIMIT 1", (new_id,))
    return inventory_items[0] if inventory_items else {"id": new_id}


@router.put("/{pid}")
def update_product(pid: int, data: ProductUpdate, claims: dict = Depends(require_auth)):
    if not _product_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    update_data = data.model_dump(exclude_unset=True)
    if 'barcode' in update_data and not (update_data.get('barcode') or '').strip():
        raise HTTPException(status_code=400, detail="条形码不能为空")
    if 'barcode' in update_data:
        update_data['barcode'] = update_data['barcode'].strip()
    existing = db.execute_query(
        "SELECT image_front, image_back, warehouse_id, owner_user_id FROM [inventory] WHERE id = ? LIMIT 1",
        (pid,),
    )
    old_front = existing[0][0] if existing else None
    old_back = existing[0][1] if existing else None
    old_warehouse_id = existing[0][2] if existing else None
    old_owner_user_id = existing[0][3] if existing else None

    if 'image_front' in update_data:
        new_front = _convert_image_payload(update_data.get('image_front'), "product_front")
        update_data['image_front'] = new_front
        update_data['image'] = new_front
        if old_front and old_front != new_front:
            delete_image_file(old_front)
    if 'image_back' in update_data:
        new_back = _convert_image_payload(update_data.get('image_back'), "product_back")
        update_data['image_back'] = new_back
        if old_back and old_back != new_back:
            delete_image_file(old_back)
    final_warehouse_id = update_data['warehouse_id'] if 'warehouse_id' in update_data else old_warehouse_id
    if final_warehouse_id is None:
        raise HTTPException(status_code=400, detail="所属仓库必填")
    if 'warehouse_id' in update_data:
        if not _warehouse_exists(final_warehouse_id):
            raise HTTPException(status_code=400, detail="所属仓库不存在")
    if 'owner_user_id' in update_data:
        new_owner_user_id = update_data['owner_user_id']
        if new_owner_user_id != old_owner_user_id and not _is_system_admin(claims):
            raise HTTPException(status_code=403, detail="仅系统管理员可修改商品归属")
        if new_owner_user_id is not None and not _user_exists(new_owner_user_id):
            raise HTTPException(status_code=400, detail="商品归属用户不存在")
    allowed_fields = {
        "name", "barcode", "category_id", "product_type_id", "owner_user_id", "warehouse_id", "price", "quantity",
        "mercari_item_id", "on_sale_quantity",
        "description", "listing_title", "listing_body", "image", "image_front", "image_back",
    }
    update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
    if update_data:
        set_sql = ", ".join([f"[{k}] = ?" for k in update_data.keys()])
        params = tuple(update_data.values()) + (pid,)
        try:
            db.execute_update(f"UPDATE [inventory] SET {set_sql} WHERE id = ?", params)
        except Exception:
            raise HTTPException(status_code=400, detail="更新失败，条形码可能重复")
    inventory_items = _query_product_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    if not inventory_items:
        raise HTTPException(status_code=400, detail="更新失败，条形码可能重复")
    return inventory_items[0]


@router.delete("/{pid}")
def delete_product(pid: int):
    if not _product_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    images = db.execute_query("SELECT image_front, image_back FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
    if images:
        delete_image_file(images[0][0])
        delete_image_file(images[0][1])
    db.execute_update("DELETE FROM [inventory] WHERE id = ?", (pid,))
    return {"message": "删除成功"}
