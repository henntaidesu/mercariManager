# -*- coding: utf-8 -*-
"""
商品表模型
"""

from typing import Dict, Any, List, Optional
from ..base_model import BaseModel
from .warehouse import WarehouseModel


class ProductModel(BaseModel):
    """商品表（图片以 Base64 格式存储于 image 字段）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'barcode': {
                'type': 'TEXT',
                'not_null': False,
                'unique': True,
                'default': None,
            },
            'sku': {
                'type': 'TEXT',
                'not_null': False,
                'unique': True,
                'default': None,
            },
            'category_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'warehouse_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'product_type_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'owner_user_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'price': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            # 人民币成本（小数），与 price（日元整数）分列存储
            'cost_cny': {
                'type': 'REAL',
                'not_null': False,
                'default': None,
            },
            'quantity': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            # 煤炉在售：单件详情 items/get 的 data.id（如 m58502999959）
            'mercari_item_id': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 与煤炉 listing 关联后的在售件数（仅 status=on_sale 计 1，其余 0）
            'on_sale_quantity': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            # 订单解析后待手动出库数量（未出库且订单非终态）
            'pending_outbound_qty': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'is_combined': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'combined_items': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 出品用：标题 / 正文（与商品名称 name、备注 description 区分）
            'listing_title': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'listing_body': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'image': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'image_front': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'image_back': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inventory_name', 'columns': ['name']},
            {'name': 'idx_inventory_category', 'columns': ['category_id']},
            {'name': 'idx_inventory_barcode', 'columns': ['barcode'], 'unique': True},
        ]

    @classmethod
    def _inventory_column_defs_for_create(cls) -> List[Dict[str, Any]]:
        return [
            {
                'name': fname,
                'type': fdef['type'],
                'primary_key': fdef.get('primary_key', False),
                'autoincrement': fdef.get('autoincrement', False),
                'not_null': fdef.get('not_null', False),
                'unique': fdef.get('unique', False),
                'default': fdef.get('default'),
            }
            for fname, fdef in cls.get_fields().items()
        ]

    @classmethod
    def _build_create_inventory_sql(cls, table_name: str) -> str:
        columns = cls._inventory_column_defs_for_create()
        column_defs: List[str] = []
        primary_keys = [f'[{col["name"]}]' for col in columns if col.get('primary_key')]
        for col in columns:
            col_name = f'[{col["name"]}]'
            col_def = f"{col_name} {col['type']}"
            if col.get('primary_key') and len(primary_keys) == 1:
                col_def += " PRIMARY KEY"
                if col.get('autoincrement'):
                    col_def += " AUTOINCREMENT"
            if col.get('not_null') and not col.get('primary_key'):
                col_def += " NOT NULL"
            if col.get('unique') and not col.get('primary_key'):
                col_def += " UNIQUE"
            if col.get('default') is not None:
                col_def += f" DEFAULT {col['default']}"
            column_defs.append(col_def)
        if len(primary_keys) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(primary_keys)})")
        return f"CREATE TABLE [{table_name}] ({', '.join(column_defs)})"

    @classmethod
    def _migrate_price_to_integer_if_needed(cls) -> None:
        """旧库 price 为 REAL 时，重建为 INTEGER（日元整数，四舍五入）。"""
        db = cls().db
        tn = cls.get_table_name()
        if not db.table_exists(tn):
            return
        cols = db.get_table_columns(tn)
        pc = next((c for c in cols if c['name'] == 'price'), None)
        if pc is None:
            return
        t = (pc.get('type') or '').upper()
        if 'INT' in t:
            return
        tmp = 'inventory__tmp_price_int'
        fnames = list(cls.get_fields().keys())
        sel_parts = [
            'CAST(ROUND(COALESCE([price],0)) AS INTEGER)' if f == 'price' else f'[{f}]'
            for f in fnames
        ]
        insert_sql = f"INSERT INTO [{tmp}] SELECT {', '.join(sel_parts)} FROM [{tn}]"
        create_sql = cls._build_create_inventory_sql(tmp)
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f'DROP TABLE IF EXISTS [{tmp}]')
            cur.execute(create_sql)
            cur.execute(insert_sql)
            cur.execute(f'DROP TABLE [{tn}]')
            cur.execute(f'ALTER TABLE [{tmp}] RENAME TO [{tn}]')
            for idx in cls.get_indexes():
                idx_name = idx.get('name', f"idx_{tn}_{idx['columns'][0]}")
                unique_kw = 'UNIQUE ' if idx.get('unique') else ''
                idx_cols = ', '.join(f'[{c}]' for c in idx['columns'])
                cur.execute(
                    f'CREATE {unique_kw}INDEX IF NOT EXISTS [{idx_name}] ON [{tn}] ({idx_cols})'
                )
            conn.commit()
        if hasattr(cls, '_cached_table_columns'):
            delattr(cls, '_cached_table_columns')
        print(f'[{tn}] price 列已迁移为 INTEGER（日元整数）')

    @classmethod
    def ensure_table_exists(cls) -> bool:
        if hasattr(cls, '_cached_table_columns'):
            delattr(cls, '_cached_table_columns')
        ok = super().ensure_table_exists()
        if not ok:
            return False
        if hasattr(cls, '_cached_table_columns'):
            delattr(cls, '_cached_table_columns')
        try:
            cls._migrate_price_to_integer_if_needed()
        except Exception as exc:
            print(f'迁移 inventory.price 为 INTEGER 失败: {exc}')
            return False
        return True

    @classmethod
    def find_with_stock(cls, keyword: Optional[str] = None, category_id: Optional[int] = None) -> List[dict]:
        """查询商品列表，附带分类名称"""
        db = cls().db
        product_fields = list(cls.get_fields().keys())
        product_select = ", ".join([f"p.[{f}] AS [{f}]" for f in product_fields])
        wh_label = WarehouseModel.sql_display_label("w")
        sql = f"""
            SELECT {product_select}, c.name as category_name, {wh_label} as warehouse_name, ptcm.product_type as product_type_name,
                   COALESCE(u.display_name, u.username) as owner_user_name
            FROM [inventory] p
            LEFT JOIN [categories] c ON c.id = p.category_id
            LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
            LEFT JOIN [product_type_category_mappings] ptcm
              ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
            LEFT JOIN [users] u ON u.id = p.owner_user_id
            WHERE 1=1
        """
        params = []
        if keyword:
            sql += " AND p.name LIKE ?"
            params.append(f"%{keyword}%")
        if category_id:
            sql += " AND p.category_id = ?"
            params.append(category_id)
        sql += " ORDER BY p.id DESC"
        rows = db.execute_query(sql, tuple(params))
        if not rows:
            return []
        field_names = product_fields + ['category_name', 'warehouse_name', 'product_type_name', 'owner_user_name']
        return [dict(zip(field_names, row)) for row in rows]
