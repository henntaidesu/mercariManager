# -*- coding: utf-8 -*-
"""库存管理 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/inventory
- 完整 URL 示例: GET /mercariV2/src/use_web/inventory/{pid}
"""
import io
import os
import time
import base64
import json
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi import Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel as PydanticModel, field_validator
from typing import Optional, List
from PIL import Image, ImageOps
from ...auth import require_auth
from ...db_manage.database import DatabaseManager
from ...image_storage import is_base64_image, save_base64_image, delete_image_file, get_image_root, save_upload_image
from ...db_manage.models.order_outbound_line import OrderOutboundLineModel

router = APIRouter()
# 公开路由：缩略图等无需登录即可访问（图片本身已通过静态文件公开）
public_router = APIRouter()
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
    "is_combined",
    "combined_items",
    "description",
    "listing_title",
    "listing_body",
    "image",
    "image_front",
    "image_back",
    "images_json",
    "created_at",
    "warehouse_id",
]


class StockInRequest(PydanticModel):
    warehouse_id: Optional[int] = None   # 不传则只更新库存，不写事务记录
    quantity: int = 1
    remark: Optional[str] = None


class InventoryCreate(PydanticModel):
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
    images: Optional[List[str]] = None

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0


class CombinedInventoryComponent(PydanticModel):
    inventory_id: int
    quantity: int = 1


class CombinedInventoryCreate(PydanticModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    product_type_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    price: int = 0
    quantity: int = 1
    description: Optional[str] = None
    listing_title: Optional[str] = None
    listing_body: Optional[str] = None
    image_front: Optional[str] = None
    image_back: Optional[str] = None
    images: Optional[List[str]] = None
    components: List[CombinedInventoryComponent]

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0


class InventoryUpdate(PydanticModel):
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
    images: Optional[List[str]] = None

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int_opt(cls, v):
        if v is None or v == '':
            return None
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None


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


def _normalize_images_input_list(items: Optional[List], field_label: str = "images") -> Optional[List[str]]:
    """None 表示调用方未传 images；空数组表示清空全部图片。"""
    if items is None:
        return None
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail=f"{field_label} 须为数组")
    if len(items) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    out: List[str] = []
    for it in items:
        if it is None:
            continue
        s = str(it).strip() if isinstance(it, str) else str(it).strip()
        if not s:
            continue
        out.append(s)
    if len(out) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    return out


def _convert_image_list_to_paths(raw_items: List[str]) -> List[str]:
    paths: List[str] = []
    for raw in raw_items:
        p = _convert_image_payload(raw, "inventory_img")
        if p:
            paths.append(p)
        if len(paths) > MAX_INVENTORY_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
            )
    return paths


def _sync_image_columns_from_paths(paths: List[str]) -> dict:
    j = json.dumps(paths, ensure_ascii=False, separators=(",", ":")) if paths else None
    front = paths[0] if paths else None
    back = paths[1] if len(paths) > 1 else None
    return {
        "image": front,
        "image_front": front,
        "image_back": back,
        "images_json": j,
    }


def _delete_paths_removed(old_paths: List[str], new_paths: List[str]) -> None:
    new_set = set(new_paths)
    for p in old_paths:
        if p and p not in new_set:
            delete_image_file(p)


def _query_inventory_with_joins(where_sql: str = "", params: tuple = ()) -> list[dict]:
    from ...db_manage.models.warehouse import WarehouseModel

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
        WHERE 1=1 {where_sql}
    """
    rows = db.execute_query(sql, tuple(params))
    items = [_enrich_inventory_api_dict(_row_to_inventory_detail(r)) for r in rows]
    from ...operation_mercari.on_sale_items_sync import enrich_inventory_rows_on_sale_quantity

    enrich_inventory_rows_on_sale_quantity(items)
    return items


def _inventory_exists(pid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [inventory] WHERE id = ? LIMIT 1", (pid,)))


def _warehouse_exists(wid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [warehouses] WHERE id = ? LIMIT 1", (wid,)))


def _user_exists(uid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [users] WHERE id = ? LIMIT 1", (uid,)))


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


def _resolve_paths_for_create(data: InventoryCreate) -> List[str]:
    if data.images is not None:
        normalized = _normalize_images_input_list(data.images, "images")
        return _convert_image_list_to_paths(normalized)
    fp = _convert_image_payload(data.image_front, "inventory_front")
    bp = _convert_image_payload(data.image_back, "inventory_back")
    paths = [p for p in [fp, bp] if p]
    if len(paths) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    return paths


def _resolve_paths_for_combined_create(data: CombinedInventoryCreate) -> List[str]:
    if data.images is not None:
        normalized = _normalize_images_input_list(data.images, "images")
        return _convert_image_list_to_paths(normalized)
    fp = _convert_image_payload(data.image_front, "inventory_front")
    bp = _convert_image_payload(data.image_back, "inventory_back")
    paths = [p for p in [fp, bp] if p]
    if len(paths) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    return paths


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


@router.get("")
def list_inventory(
    keyword: Optional[str] = None,
    category_id: Optional[int] = None,
    product_type_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    in_stock_only: bool = False,
    warehouse_assigned_only: bool = False,
    no_image_only: bool = False,
    combined_only: bool = False,
):
    where_parts = []
    params = []
    kw = (keyword or "").strip()
    if kw:
        where_parts.append("AND (p.name LIKE ? OR CAST(p.id AS TEXT) LIKE ?)")
        params.append(f"%{kw}%")
        params.append(f"%{kw}%")
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
    if warehouse_assigned_only:
        where_parts.append("AND p.warehouse_id IS NOT NULL")
    if no_image_only:
        where_parts.append(f"AND NOT {_sql_inventory_has_image_condition()}")
    if combined_only:
        where_parts.append("AND COALESCE(p.is_combined, 0) = 1")
    where_sql = " " + " ".join(where_parts) + " ORDER BY p.id DESC"
    return _query_inventory_with_joins(where_sql, tuple(params))


@router.get("/barcode/{barcode}")
def find_by_barcode(barcode: str):
    """根据条形码精确查找商品（用于连续扫码流程）"""
    inventory_items = _query_inventory_with_joins(" AND p.barcode = ? LIMIT 1", (barcode.strip(),))
    if not inventory_items:
        return {"found": False, "inventory": None}
    return {"found": True, "inventory": inventory_items[0]}


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
    rows = db.execute_query(
        "SELECT id, image_front, image, image_back, images_json FROM [inventory]"
    )
    best_id = None
    best_distance = 999

    for pid, image_front, image, image_back, images_json in rows:
        candidates = _legacy_paths_from_db_columns(image_front, image, image_back, images_json)
        row_best = 999
        for path in candidates:
            candidate_img = _load_image_for_match(path)
            if candidate_img is None:
                continue
            distance = _hamming_distance(query_hash, _to_dhash(candidate_img))
            if distance < row_best:
                row_best = distance
        if row_best < 999:
            if row_best < best_distance:
                best_distance = row_best
                best_id = pid

    if best_id is None:
        return {"found": False, "inventory": None, "distance": None}

    # 经验阈值：dHash 64bit，距离越小越像；>18 误匹配概率明显增高
    if best_distance > 18:
        return {"found": False, "inventory": None, "distance": best_distance}

    matched = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (best_id,))
    if not matched:
        return {"found": False, "inventory": None, "distance": best_distance}
    return {"found": True, "inventory": matched[0], "distance": best_distance}


@router.post("/upload-image")
async def upload_inventory_image(file: UploadFile = File(...)):
    """无码入库等场景：先 multipart 上传落盘，再提交表单时只传 /imges/ 路径（避免保存时再传大体积 base64）。"""
    path = await save_upload_image(file, prefix="inv_nb")
    return {"path": path}


@router.post("/combine")
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


@router.post("/{pid}/stock-in")
def stock_in_inventory(pid: int, data: StockInRequest):
    """连续扫码入库：库存 +N；若提供 warehouse_id 则同时写入事务记录"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="入库数量必须大于0")
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT is_combined, combined_items FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
            meta = cur.fetchone()
            if not meta:
                raise HTTPException(status_code=404, detail="商品不存在")
            if int(meta[0] or 0):
                _adjust_combined_source_stock(cur, _parse_combined_items(meta[1]), int(data.quantity))
            cur.execute(
                "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) + ? WHERE id = ?",
                (data.quantity, pid),
            )
            if cur.rowcount <= 0:
                raise HTTPException(status_code=500, detail="库存更新失败")
            if data.warehouse_id:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
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
            conn.commit()
    except HTTPException:
        raise
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}


@router.post("/{pid}/stock-out")
def stock_out_inventory(pid: int, data: StockInRequest):
    """连续扫码出库：库存 -N；若提供 warehouse_id 则同时写入事务记录"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="出库数量必须大于0")
    current_qty_row = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
    current_qty = (current_qty_row[0][0] if current_qty_row else 0) or 0
    if current_qty < data.quantity:
        raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT is_combined, combined_items, quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
            meta = cur.fetchone()
            if not meta:
                raise HTTPException(status_code=404, detail="商品不存在")
            if int(meta[2] or 0) < data.quantity:
                raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{int(meta[2] or 0)}")
            if int(meta[0] or 0):
                _adjust_combined_source_stock(cur, _parse_combined_items(meta[1]), -int(data.quantity))
            cur.execute(
                "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) - ? WHERE id = ?",
                (data.quantity, pid),
            )
            if cur.rowcount <= 0:
                raise HTTPException(status_code=500, detail="库存更新失败")
            if data.warehouse_id:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
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
            conn.commit()
    except HTTPException:
        raise
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}


@router.get("/{pid}/pending-outbound-lines")
def list_inventory_pending_outbound_lines(pid: int):
    """库存展开：该商品在非终态订单中尚未出库的明细行。"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    items = OrderOutboundLineModel.list_pending_for_inventory(pid)
    return {"inventory_id": pid, "items": items}


@router.get("/{pid}")
def get_inventory(pid: int):
    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    if not inventory_items:
        raise HTTPException(status_code=404, detail="商品不存在")
    return inventory_items[0]


@router.post("")
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
                mercari_item_id, on_sale_quantity, pending_outbound_qty,
                description, listing_title, listing_body, image, image_front, image_back, images_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


@router.put("/{pid}")
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
    allowed_fields = {
        "name", "barcode", "category_id", "product_type_id", "owner_user_id", "warehouse_id", "price",
        "quantity",
        "mercari_item_id", "on_sale_quantity",
        "description", "listing_title", "listing_body", "image", "image_front", "image_back", "images_json",
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


@router.delete("/{pid}")
def delete_inventory(pid: int):
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    images = db.execute_query(
        """
        SELECT image, image_front, image_back, images_json, is_combined, combined_items, quantity
        FROM [inventory] WHERE id = ? LIMIT 1
        """,
        (pid,),
    )
    if images:
        paths = _legacy_paths_from_db_columns(images[0][1], images[0][0], images[0][2], images[0][3])
        for p in paths:
            delete_image_file(p)
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            if images and int(images[0][4] or 0):
                _adjust_combined_source_stock(
                    cur,
                    _parse_combined_items(images[0][5]),
                    -int(images[0][6] or 0),
                )
            cur.execute("DELETE FROM [inventory] WHERE id = ?", (pid,))
            conn.commit()
    except HTTPException:
        raise
    return {"message": "删除成功"}
