# -*- coding: utf-8 -*-
"""仓库（货架位）管理 API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/warehouses
- 完整 URL 示例: GET /mercariV2/src/use_web/warehouses/
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel
from typing import Optional
from ...db_manage.database import DatabaseManager
from ...db_manage.models.warehouse import WarehouseModel

router = APIRouter()
db = DatabaseManager()


class WarehouseCreate(PydanticModel):
    name: Optional[str] = None  # 货架号（可重复）；可为空表示暂未编号
    warehouse: Optional[str] = "默认仓库"
    shelf_name: Optional[str] = None  # 货架名称（展示）
    location: Optional[str] = None
    description: Optional[str] = None


class WarehouseUpdate(PydanticModel):
    name: Optional[str] = None
    warehouse: Optional[str] = None
    shelf_name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class RenameWarehouseGroupBody(PydanticModel):
    """将同一展示仓库名下的所有货架位批量改到新仓库名（仅改 warehouse 字段）"""
    old_warehouse: str
    new_warehouse: str


class MigrateInventoryBody(PydanticModel):
    target_warehouse_id: int


class RenameShelfNameGroupBody(PydanticModel):
    """同一仓库下、同一货架名称（shelf_name）分组批量改为新名称"""
    warehouse: str
    old_shelf_name: Optional[str] = None  # 空串 / None 表示「未设置货架名称」分组
    new_shelf_name: Optional[str] = None  # 空串 / None 表示清空为未设置


def _norm_shelf_code(n: Optional[str]) -> Optional[str]:
    if n is None:
        return None
    t = str(n).strip()
    return t if t else None


def _norm_shelf_name_key(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    t = str(s).strip()
    return t if t else None


def _serialize(wh: WarehouseModel) -> dict:
    d = wh.to_dict()
    d.update(WarehouseModel.get_stats(wh.id))
    return d


@router.get("")
def list_warehouses():
    return [_serialize(w) for w in WarehouseModel.find_all(order_by="id ASC")]


def _safe_remove_default_template_shelf(name: str, exclude_id: int) -> None:
    """
    在非默认仓库新建同名货架后，若默认仓库仍有同名「模板」货架则删除之，
    避免列表里长期保留重复名称；有出入库或库存占用时不删。
    """
    default_key = WarehouseModel.normalize_warehouse_key(None)
    tmpl = WarehouseModel.find_by_warehouse_and_name(default_key, name)
    if not tmpl or tmpl.id == exclude_id:
        return
    wid = tmpl.id
    has_tx = db.execute_query(
        "SELECT 1 FROM [transactions] WHERE warehouse_id = ? OR target_warehouse_id = ? LIMIT 1",
        (wid, wid),
    )
    if has_tx:
        return
    has_inv = db.execute_query(
        "SELECT 1 FROM [inventory] WHERE warehouse_id = ? LIMIT 1",
        (wid,),
    )
    if has_inv:
        return
    has_cost = db.execute_query(
        "SELECT 1 FROM [cost_records] WHERE warehouse_id = ? LIMIT 1",
        (wid,),
    )
    if has_cost:
        return
    tmpl.delete()


@router.post("")
def create_warehouse(data: WarehouseCreate):
    wh_key = WarehouseModel.normalize_warehouse_key(data.warehouse)
    nm = _norm_shelf_code(data.name)
    sn = (data.shelf_name or "").strip() or None
    wh = WarehouseModel(
        name=nm,
        warehouse=wh_key,
        shelf_name=sn,
        location=data.location,
        description=data.description
    )
    if not wh.save():
        raise HTTPException(status_code=500, detail="保存失败")
    default_key = WarehouseModel.normalize_warehouse_key(None)
    if wh_key != default_key and nm:
        _safe_remove_default_template_shelf(nm, wh.id)
    return _serialize(wh)


@router.put("/rename-group")
def rename_warehouse_group(data: RenameWarehouseGroupBody):
    old_key = WarehouseModel.normalize_warehouse_key(data.old_warehouse)
    new_key = WarehouseModel.normalize_warehouse_key(data.new_warehouse)
    if old_key == new_key:
        raise HTTPException(status_code=400, detail="新仓库名称与当前相同")
    all_rows = WarehouseModel.find_all(order_by="id ASC")

    def row_wh_key(w: WarehouseModel) -> str:
        return WarehouseModel.normalize_warehouse_key(w.warehouse)

    targets = [w for w in all_rows if row_wh_key(w) == old_key]
    if not targets:
        raise HTTPException(status_code=404, detail="未找到该仓库")
    for w in targets:
        w.warehouse = new_key
        if not w.save():
            raise HTTPException(status_code=500, detail="保存失败")
    return {"message": "仓库名称已更新", "updated": len(targets)}


@router.put("/rename-shelf-name-group")
def rename_shelf_name_group(data: RenameShelfNameGroupBody):
    wh_key = WarehouseModel.normalize_warehouse_key(data.warehouse)
    old_key = _norm_shelf_name_key(data.old_shelf_name)
    new_key = _norm_shelf_name_key(data.new_shelf_name)
    if old_key == new_key:
        raise HTTPException(status_code=400, detail="新货架名称与当前相同")

    def row_wh_key(w: WarehouseModel) -> str:
        return WarehouseModel.normalize_warehouse_key(w.warehouse)

    def row_sn_key(w: WarehouseModel) -> Optional[str]:
        return _norm_shelf_name_key(w.shelf_name)

    all_rows = WarehouseModel.find_all(order_by="id ASC")
    targets = [w for w in all_rows if row_wh_key(w) == wh_key and row_sn_key(w) == old_key]
    if not targets:
        raise HTTPException(status_code=404, detail="未找到该货架名称分组")
    for w in targets:
        w.shelf_name = new_key
        if not w.save():
            raise HTTPException(status_code=500, detail="保存失败")
    return {"message": "货架名称已更新", "updated": len(targets)}


@router.post("/{wid}/migrate-inventory")
def migrate_inventory_to_shelf(wid: int, data: MigrateInventoryBody):
    """将源货架位 ID 的业务关联整体迁移到目标货架位 ID。"""
    tid = int(data.target_warehouse_id)
    if tid == wid:
        raise HTTPException(status_code=400, detail="目标货架不能与当前相同")
    src = WarehouseModel.find_by_id(id=wid)
    dst = WarehouseModel.find_by_id(id=tid)
    if not src or not dst:
        raise HTTPException(status_code=404, detail="货架不存在")
    try:
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            # 库存归属迁移（库存管理主数据）
            cur.execute(
                "UPDATE [inventory] SET warehouse_id = ? WHERE warehouse_id = ?",
                (tid, wid),
            )
            moved_inventory = cur.rowcount
            # 出入库记录迁移：来源仓
            cur.execute(
                "UPDATE [transactions] SET warehouse_id = ? WHERE warehouse_id = ?",
                (tid, wid),
            )
            moved_tx_from = cur.rowcount
            # 出入库记录迁移：目标仓（transfer 场景）
            cur.execute(
                "UPDATE [transactions] SET target_warehouse_id = ? WHERE target_warehouse_id = ?",
                (tid, wid),
            )
            moved_tx_to = cur.rowcount
            # 成本记录归属迁移
            cur.execute(
                "UPDATE [cost_records] SET warehouse_id = ? WHERE warehouse_id = ?",
                (tid, wid),
            )
            moved_cost = cur.rowcount
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"迁移失败: {e}")
    return {
        "message": "迁移完成",
        "moved": moved_inventory,
        "moved_inventory": moved_inventory,
        "moved_transactions_from": moved_tx_from,
        "moved_transactions_to": moved_tx_to,
        "moved_cost_records": moved_cost,
    }


@router.put("/{wid}")
def update_warehouse(wid: int, data: WarehouseUpdate):
    wh = WarehouseModel.find_by_id(id=wid)
    if not wh:
        raise HTTPException(status_code=404, detail="仓库不存在")
    patch = data.model_dump(exclude_unset=True)
    next_wh = WarehouseModel.normalize_warehouse_key(
        patch["warehouse"] if "warehouse" in patch else wh.warehouse
    )
    next_name = _norm_shelf_code(patch["name"]) if "name" in patch else wh.name
    if "name" in patch:
        wh.name = next_name
    if "warehouse" in patch:
        wh.warehouse = next_wh
    if "shelf_name" in patch:
        wh.shelf_name = (patch["shelf_name"] or "").strip() or None
    if "location" in patch:
        wh.location = patch["location"]
    if "description" in patch:
        wh.description = patch["description"]
    wh.save()
    return _serialize(wh)


@router.delete("/{wid}")
def delete_warehouse(wid: int):
    wh = WarehouseModel.find_by_id(id=wid)
    if not wh:
        raise HTTPException(status_code=404, detail="仓库不存在")
    # 仅删除货架本身；业务数据不删除
    # 库存中的关联置空，避免仍指向已删除货架
    db.execute_update("UPDATE [inventory] SET warehouse_id = NULL WHERE warehouse_id = ?", (wid,))
    wh.delete()
    return {"message": "删除成功（已保留库存/出入库/成本记录）"}
