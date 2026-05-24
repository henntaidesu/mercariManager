# -*- coding: utf-8 -*-
"""
数据库管理器 - 统一管理所有表模型
"""

from typing import List, Type
from .base_model import BaseModel
from .database import DatabaseManager
from .models import (
    CategoryModel,
    WarehouseModel,
    InventoryModel,
    TransactionModel,
    UserModel,
    CostRecordModel,
    CostExpenseModel,
    OrderModel,
    OrderOutboundLineModel,
    MeiluAccountModel,
    OnSaleItemModel,
    ProductTypeCategoryMappingModel,
    ConfigEntryModel,
    TodoItemModel,
    NotificationModel,
    BundlePurchaseRequestModel,
)


class DBManager:
    """数据库管理器 - 统一注册、初始化所有表"""

    def __init__(self):
        self.db = DatabaseManager()
        self.models: List[Type[BaseModel]] = self._get_all_models()

    def _migrate_warehouses_composite_unique(self) -> bool:
        """
        历史表在 [name] 上有全局 UNIQUE，导致不同仓库不能建同名货架。
        重建表为 (warehouse, name) 组合唯一，并保留 id 以维护外键。
        """
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        if db.execute_query(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_warehouses_warehouse_name'"
        ):
            return True
        print("正在迁移 warehouses：货架名称改为「仓库+货架」组合唯一 ...")
        col_names = [c["name"] for c in db.get_table_columns("warehouses")]
        if "id" not in col_names or "name" not in col_names:
            print("[WARN] warehouses 表缺少 id/name，跳过组合唯一迁移")
            return True
        if "warehouse" not in col_names:
            print("[WARN] warehouses 表缺少 warehouse 列，跳过组合唯一迁移")
            return True
        ordered = ["id", "name", "warehouse", "location", "description", "created_at"]
        present = [c for c in ordered if c in col_names]
        if not present:
            print("[WARN] warehouses 无可用列，跳过组合唯一迁移")
            return True
        insert_cols = ", ".join(f"[{c}]" for c in present)
        select_parts = []
        for c in present:
            if c == "warehouse":
                select_parts.append(
                    "COALESCE(NULLIF(TRIM([warehouse]), ''), '默认仓库')"
                )
            else:
                select_parts.append(f"[{c}]")
        select_sql = ", ".join(select_parts)
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    """
                    CREATE TABLE [warehouses__mig] (
                        [id] INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        [name] TEXT NOT NULL,
                        [warehouse] TEXT DEFAULT '默认仓库',
                        [location] TEXT,
                        [description] TEXT,
                        [created_at] DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cur.execute(
                    f"INSERT INTO [warehouses__mig] ({insert_cols}) "
                    f"SELECT {select_sql} FROM [warehouses]"
                )
                cur.execute("DROP TABLE [warehouses]")
                cur.execute("ALTER TABLE [warehouses__mig] RENAME TO [warehouses]")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                    "ON [warehouses]([warehouse], [name])"
                )
                conn.commit()
                cur.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            print(f"[错误] warehouses 组合唯一迁移失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(WarehouseModel, cache_attr):
            try:
                delattr(WarehouseModel, cache_attr)
            except Exception:
                pass
        print("[OK] warehouses 组合唯一迁移完成")
        return True

    def _migrate_transactions_product_id_to_inventory_id(self) -> bool:
        """出入库记录表：product_id 列重命名为 inventory_id（与 inventory 表一致）。"""
        db = self.db
        if not db.table_exists("transactions"):
            return True
        cols = {c["name"] for c in db.get_table_columns("transactions")}
        if "inventory_id" in cols:
            return True
        if "product_id" not in cols:
            return True
        print("正在迁移 transactions：product_id -> inventory_id ...")
        try:
            db.execute_update(
                "ALTER TABLE [transactions] RENAME COLUMN [product_id] TO [inventory_id]"
            )
            db.execute_update("DROP INDEX IF EXISTS idx_transactions_product")
            db.execute_update(
                "CREATE INDEX IF NOT EXISTS idx_transactions_inventory "
                "ON [transactions]([inventory_id])"
            )
        except Exception as e:
            print(f"[错误] transactions.product_id 迁移失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(TransactionModel, cache_attr):
            try:
                delattr(TransactionModel, cache_attr)
            except Exception:
                pass
        print("[OK] transactions.inventory_id 迁移完成")
        return True

    def _migrate_warehouses_name_nullable(self) -> bool:
        """货架号 name 允许为空（添加货架可不填编号）"""
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        cols = db.get_table_columns("warehouses")
        name_col = next((c for c in cols if c.get("name") == "name"), None)
        if not name_col or not name_col.get("notnull"):
            return True
        print("正在迁移 warehouses：货架号 name 允许为空 ...")
        col_names = [c["name"] for c in sorted(cols, key=lambda x: x.get("cid", 0))]
        insert_cols = ", ".join(f"[{c}]" for c in col_names)
        select_sql = ", ".join(f"[{c}]" for c in col_names)
        # 重建为 name TEXT 可空，保留其余列定义与数据
        type_by_name = {c["name"]: c.get("type", "TEXT") for c in cols}
        pk_def = "[id] INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT"
        parts = [pk_def]
        for c in col_names:
            if c == "id":
                continue
            ctype = type_by_name.get(c, "TEXT")
            if c == "name":
                parts.append("[name] TEXT")
            elif c == "warehouse":
                parts.append("[warehouse] TEXT DEFAULT '默认仓库'")
            elif c == "created_at":
                parts.append("[created_at] DATETIME DEFAULT CURRENT_TIMESTAMP")
            else:
                parts.append(f"[{c}] {ctype}")
        create_body = ", ".join(parts)
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(f"CREATE TABLE [warehouses__mig_nullname] ({create_body})")
                cur.execute(
                    f"INSERT INTO [warehouses__mig_nullname] ({insert_cols}) "
                    f"SELECT {select_sql} FROM [warehouses]"
                )
                cur.execute("DROP TABLE [warehouses]")
                cur.execute("ALTER TABLE [warehouses__mig_nullname] RENAME TO [warehouses]")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                    "ON [warehouses]([warehouse], [name])"
                )
                conn.commit()
                cur.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            print(f"[错误] warehouses name 可空迁移失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(WarehouseModel, cache_attr):
            try:
                delattr(WarehouseModel, cache_attr)
            except Exception:
                pass
        print("[OK] warehouses name 可空迁移完成")
        return True

    def _migrate_warehouses_drop_shelf_code_unique(self) -> bool:
        """同一仓库下允许重复货架号：移除 (warehouse, name) 唯一索引，改为普通索引。"""
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        info = db.execute_query(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_warehouses_warehouse_name'"
        )
        if not info:
            db.execute_update(
                "CREATE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                "ON [warehouses]([warehouse], [name])"
            )
            return True
        sql_def = (info[0][0] or "").upper()
        if "UNIQUE" not in sql_def:
            return True
        print("正在迁移 warehouses：允许同仓库重复货架号 ...")
        try:
            db.execute_update("DROP INDEX idx_warehouses_warehouse_name")
            db.execute_update(
                "CREATE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                "ON [warehouses]([warehouse], [name])"
            )
        except Exception as e:
            print(f"[错误] warehouses 去唯一约束迁移失败: {e}")
            return False
        print("[OK] warehouses 去唯一约束迁移完成")
        return True

    def _migrate_ptcm_to_independent_module(self) -> bool:
        """
        将 product_type_category_mappings 从 product_type_id 迁移到纯文本 product_type。
        独立模块：不再依赖 game_types / 其他表。
        """
        db = self.db
        if not db.table_exists("product_type_category_mappings"):
            return True
        cols = [c["name"] for c in db.get_table_columns("product_type_category_mappings")]
        if "product_type" in cols:
            return True
        if "product_type_id" not in cols:
            return True
        try:
            db.execute_update("ALTER TABLE [product_type_category_mappings] ADD COLUMN [product_type] TEXT")
            source_table = None
            if db.table_exists("game_types"):
                source_table = "game_types"
            elif db.table_exists("product_types"):
                source_table = "product_types"
            if source_table:
                db.execute_update(
                    f"""
                    UPDATE [product_type_category_mappings]
                    SET [product_type] = (
                        SELECT t.[name]
                        FROM [{source_table}] t
                        WHERE t.[id] = [product_type_category_mappings].[product_type_id]
                    )
                    WHERE [product_type] IS NULL
                    """
                )
            db.execute_update(
                """
                UPDATE [product_type_category_mappings]
                SET [product_type] = '类型' || CAST([product_type_id] AS TEXT)
                WHERE [product_type] IS NULL OR TRIM([product_type]) = ''
                """
            )
            print("[OK] product_type_category_mappings 已迁移为独立商品类型文本字段")
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 独立化迁移失败: {e}")
            return False

    def _migrate_ptcm_category_field_to_mapping_id(self) -> bool:
        """
        将 product_type_category_mappings.category_field 迁移为 mapping_id。
        """
        db = self.db
        if not db.table_exists("product_type_category_mappings"):
            return True
        cols = [c["name"] for c in db.get_table_columns("product_type_category_mappings")]
        if "mapping_id" in cols:
            return True
        if "category_field" not in cols:
            return True
        try:
            db.execute_update("ALTER TABLE [product_type_category_mappings] ADD COLUMN [mapping_id] TEXT")
            db.execute_update(
                """
                UPDATE [product_type_category_mappings]
                SET [mapping_id] = [category_field]
                WHERE [mapping_id] IS NULL OR TRIM([mapping_id]) = ''
                """
            )
            print("[OK] product_type_category_mappings 已迁移 category_field -> mapping_id")
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 字段迁移失败: {e}")
            return False

    def _migrate_ptcm_mapping_id_as_primary_key(self) -> bool:
        """
        将 product_type_category_mappings 的主键改为 mapping_id（TEXT）。
        """
        db = self.db
        tn = "product_type_category_mappings"
        if not db.table_exists(tn):
            return True
        cols = db.get_table_columns(tn)
        mapping_col = next((c for c in cols if c["name"] == "mapping_id"), None)
        if not mapping_col:
            return True
        if mapping_col.get("pk"):
            return True
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    """
                    CREATE TABLE [product_type_category_mappings__mig_pk] (
                        [mapping_id] TEXT NOT NULL PRIMARY KEY,
                        [product_type] TEXT NOT NULL,
                        [description] TEXT,
                        [created_at] DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT OR IGNORE INTO [product_type_category_mappings__mig_pk]
                    ([mapping_id], [product_type], [description], [created_at])
                    SELECT
                        TRIM([mapping_id]),
                        COALESCE(NULLIF(TRIM([product_type]), ''), ''),
                        [description],
                        [created_at]
                    FROM [product_type_category_mappings]
                    WHERE TRIM(COALESCE([mapping_id], '')) != ''
                    """
                )
                cur.execute(f"DROP TABLE [{tn}]")
                cur.execute(
                    f"ALTER TABLE [product_type_category_mappings__mig_pk] RENAME TO [{tn}]"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ptcm_product_type ON [product_type_category_mappings]([product_type])"
                )
                conn.commit()
                cur.execute("PRAGMA foreign_keys=ON")
            print("[OK] product_type_category_mappings 已改为 mapping_id 主键")
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 主键迁移失败: {e}")
            return False

    def _get_all_models(self) -> List[Type[BaseModel]]:
        """按依赖顺序返回所有模型类"""
        return [
            UserModel,        # 无外键依赖（登录依赖）
            ConfigEntryModel,  # 键值配置（出品默认值等）
            CategoryModel,    # 无外键依赖
            WarehouseModel,   # 无外键依赖
            InventoryModel,   # 依赖 categories
            TransactionModel, # 依赖 inventory, warehouses
            CostRecordModel,  # 依赖 warehouses（可为空）
            CostExpenseModel,  # 成本支出
            OrderModel,       # 订单管理
            OrderOutboundLineModel,  # 订单解析出的待出库明细（依赖 orders / inventory 逻辑）
            MeiluAccountModel,  # 煤炉账号
            OnSaleItemModel,  # 在售商品缓存
            TodoItemModel,  # 待办事项缓存（依赖 meilu_accounts，仅顺序习惯）
            NotificationModel,  # お知らせ通知缓存（依赖 meilu_accounts，仅顺序习惯）
            BundlePurchaseRequestModel,  # 合并购买请求缓存（依赖 notifications，仅顺序习惯）
            ProductTypeCategoryMappingModel,  # 商品类型与类别字段映射
        ]

    def initialize_database(self) -> bool:
        """初始化数据库：按顺序检查/创建所有表，删除代码中不存在的表"""
        print("正在初始化数据库...")

        # 表重命名迁移：products -> inventory
        if self.db.table_exists("products") and not self.db.table_exists("inventory"):
            print("检测到旧表 products，正在迁移为 inventory ...")
            self.db.execute_update("ALTER TABLE [products] RENAME TO [inventory]")
        if not self._migrate_transactions_product_id_to_inventory_id():
            return False
        if not self._migrate_ptcm_to_independent_module():
            return False
        if not self._migrate_ptcm_category_field_to_mapping_id():
            return False
        if not self._migrate_ptcm_mapping_id_as_primary_key():
            return False

        defined_tables = {m.get_table_name() for m in self.models}
        db_tables = self.db.get_all_tables()

        # 删除代码中已移除的表
        to_drop = [t for t in db_tables if t not in defined_tables and t != "product_types"]
        for table_name in to_drop:
            print(f"发现废弃表 {table_name}，正在删除...")
            self.db.drop_table(table_name)

        success, failed = 0, []
        for model_class in self.models:
            table_name = model_class.get_table_name()
            try:
                if model_class.ensure_table_exists():
                    success += 1
                else:
                    failed.append(table_name)
            except Exception as e:
                failed.append(table_name)
                print(f"表 {table_name} 初始化异常: {e}")

        total = len(self.models)
        if not failed:
            print(f"[OK] 数据库初始化成功: {success}/{total} 个表")
        else:
            print(f"[WARN] 数据库初始化完成: {success}/{total}，失败: {', '.join(failed)}")
            return False

        if not self._migrate_warehouses_composite_unique():
            return False
        if not self._migrate_warehouses_name_nullable():
            return False
        if not self._migrate_warehouses_drop_shelf_code_unique():
            return False
        return True

    def check_integrity(self) -> bool:
        """检查所有表结构完整性"""
        for model_class in self.models:
            table_name = model_class.get_table_name()
            if not self.db.table_exists(table_name):
                return False
            existing = {col['name'] for col in self.db.get_table_columns(table_name)}
            if set(model_class.get_fields().keys()) - existing:
                return False
        print("[OK] 所有表完整性检查通过")
        return True

    def get_statistics(self) -> dict:
        """获取各表记录数统计"""
        stats = {'tables': {}, 'total_records': 0}
        for model_class in self.models:
            count = model_class.count()
            stats['tables'][model_class.get_table_name()] = count
            stats['total_records'] += count
        return stats


# 全局单例
_db_manager = DBManager()
_initialized = False


def init_database() -> bool:
    """初始化数据库的便捷函数"""
    global _initialized
    if _initialized:
        return True
    result = _db_manager.initialize_database()
    if result:
        _initialized = True
    return result


def get_db_manager() -> DBManager:
    return _db_manager
