# -*- coding: utf-8 -*-
"""
数据库管理核心类
"""

import sqlite3
import os
import threading
from contextlib import contextmanager
from typing import List, Dict, Any, Optional

from src.app_paths import backend_root_str


class DatabaseManager:
    """数据库管理器 - 单例模式"""

    _instance = None
    _lock = threading.Lock()
    _tlocal = threading.local()  # 每线程的活动事务连接（transaction() 内复用）

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            # mercariDB.db 放在 backend 根目录（冻结后与 exe 同目录）
            self.db_path = os.path.join(backend_root_str(), 'mercariDB.db')
            self.initialized = True
            self._setup_database()

    def _setup_database(self):
        """设置数据库配置"""
        with self.get_connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=1000')
            conn.execute('PRAGMA temp_store=MEMORY')
            conn.execute('PRAGMA foreign_keys=ON')
            conn.commit()

    def _active_transaction_conn(self):
        """当前线程处于 transaction() 中时返回事务连接，否则 None"""
        return getattr(self._tlocal, 'conn', None)

    @contextmanager
    def get_connection(self):
        """获取数据库连接上下文管理器（处于事务中时复用事务连接，由 transaction() 统一提交/关闭）"""
        active = self._active_transaction_conn()
        if active is not None:
            yield active
            return
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """事务上下文：块内所有 execute_* 在同一连接上执行，结束时统一提交，异常时回滚。

        嵌套调用时直接加入外层事务。不使用 transaction() 的代码路径行为完全不变。
        """
        active = self._active_transaction_conn()
        if active is not None:
            # 嵌套事务：直接加入外层事务
            yield active
            return
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.isolation_level = None  # 手动管理事务
        conn.execute('BEGIN IMMEDIATE')
        self._tlocal.conn = conn
        try:
            yield conn
            conn.execute('COMMIT')
        except BaseException:
            try:
                conn.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise
        finally:
            self._tlocal.conn = None
            conn.close()

    def execute_query(self, sql: str, params: tuple = ()) -> List[tuple]:
        """执行查询语句"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()

    def execute_update(self, sql: str, params: tuple = ()) -> int:
        """执行更新语句，返回受影响的行数"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if self._active_transaction_conn() is None:
                conn.commit()
            return cursor.rowcount

    def execute_insert(self, sql: str, params: tuple = ()) -> Optional[int]:
        """执行插入语句，返回最后插入的行ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if self._active_transaction_conn() is None:
                conn.commit()
            return cursor.lastrowid

    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """执行批量操作"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(sql, params_list)
            if self._active_transaction_conn() is None:
                conn.commit()
            return cursor.rowcount

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
        result = self.execute_query(sql, (table_name,))
        return len(result) > 0

    def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """获取表的列信息"""
        if not self.table_exists(table_name):
            return []
        result = self.execute_query(f"PRAGMA table_info({table_name})")
        return [
            {'cid': r[0], 'name': r[1], 'type': r[2],
             'notnull': bool(r[3]), 'default_value': r[4], 'pk': bool(r[5])}
            for r in result
        ]

    def create_table(self, table_name: str, columns: List[Dict[str, Any]],
                     indexes: List[Dict[str, Any]] = None) -> bool:
        """创建表"""
        try:
            column_defs = []
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

            sql = f"CREATE TABLE IF NOT EXISTS [{table_name}] ({', '.join(column_defs)})"
            self.execute_update(sql)

            if indexes:
                for idx in indexes:
                    idx_name = idx.get('name', f"idx_{table_name}_{idx['columns'][0]}")
                    unique_kw = "UNIQUE " if idx.get('unique') else ""
                    idx_cols = ', '.join([f'[{c}]' for c in idx['columns']])
                    self.execute_update(
                        f"CREATE {unique_kw}INDEX IF NOT EXISTS {idx_name} ON [{table_name}] ({idx_cols})"
                    )
            return True
        except Exception as e:
            print(f"创建表 {table_name} 失败: {e}")
            return False

    def add_column(self, table_name: str, column_def: Dict[str, Any]) -> bool:
        """添加列到现有表"""
        try:
            col_sql = f"[{column_def['name']}] {column_def['type']}"
            if column_def.get('not_null'):
                col_sql += " NOT NULL"
            if column_def.get('default') is not None:
                col_sql += f" DEFAULT {column_def['default']}"
            self.execute_update(f"ALTER TABLE [{table_name}] ADD COLUMN {col_sql}")
            return True
        except Exception as e:
            print(f"添加列到表 {table_name} 失败: {e}")
            return False

    def drop_column(self, table_name: str, column_name: str) -> bool:
        """删除表中的列"""
        try:
            version = self.execute_query("SELECT sqlite_version()")[0][0]
            parts = [int(x) for x in version.split('.')]
            if parts[0] > 3 or (parts[0] == 3 and parts[1] >= 35):
                self.execute_update(f"ALTER TABLE [{table_name}] DROP COLUMN [{column_name}]")
                return True
            return self._drop_column_recreate_table(table_name, column_name)
        except Exception as e:
            print(f"删除列 {column_name} 失败: {e}")
            return False

    def _drop_column_recreate_table(self, table_name: str, column_name: str) -> bool:
        """通过重建表来删除列（旧版 SQLite 兼容）"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                columns = self.get_table_columns(table_name)
                keep_columns = [col for col in columns if col['name'] != column_name]
                keep_names = [f"[{col['name']}]" for col in keep_columns]
                keep_names_str = ", ".join(keep_names)
                tmp = f"{table_name}_tmp_{abs(hash(column_name)) % 1000000}"

                col_defs = []
                pks = []
                for col in keep_columns:
                    d = f"[{col['name']}] {col['type']}"
                    if col.get('pk'):
                        if sum(1 for c in keep_columns if c.get('pk')) == 1:
                            d += " PRIMARY KEY"
                        else:
                            pks.append(f"[{col['name']}]")
                    if col.get('notnull') and not col.get('pk'):
                        d += " NOT NULL"
                    if col.get('default_value') is not None:
                        d += f" DEFAULT {col['default_value']}"
                    col_defs.append(d)
                if len(pks) > 1:
                    col_defs.append(f"PRIMARY KEY ({', '.join(pks)})")

                cursor.execute(f"CREATE TABLE [{tmp}] ({', '.join(col_defs)})")
                cursor.execute(f"INSERT INTO [{tmp}] ({keep_names_str}) SELECT {keep_names_str} FROM [{table_name}]")
                cursor.execute(f"DROP TABLE [{table_name}]")
                cursor.execute(f"ALTER TABLE [{tmp}] RENAME TO [{table_name}]")
                conn.commit()
                return True
        except Exception as e:
            print(f"重建表删除列失败: {e}")
            return False

    def get_all_tables(self) -> List[str]:
        """获取数据库中所有表名"""
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        return [r[0] for r in self.execute_query(sql)]

    def drop_table(self, table_name: str) -> bool:
        """删除表"""
        try:
            self.execute_update(f"DROP TABLE IF EXISTS [{table_name}]")
            return True
        except Exception as e:
            print(f"删除表 {table_name} 失败: {e}")
            return False

    def get_database_info(self) -> Dict[str, Any]:
        """获取数据库信息"""
        tables = self.get_all_tables()
        return {
            'db_path': self.db_path,
            'tables': [{'name': t, 'columns': self.get_table_columns(t)} for t in tables]
        }
