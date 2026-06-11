# -*- coding: utf-8 -*-
"""Gotion 表格管理 API 路由（对应前端 /gotion 页面）。

Notion 风格多维表格：用户自定义表（父子两级）+ 自定义列（文本/数字/单选/标签/链接/关联表格）+ JSON 行数据。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/gotion
- 完整 URL 示例:
    GET    /mercariV2/src/use_web/gotion/tables
    POST   /mercariV2/src/use_web/gotion/tables
    PATCH  /mercariV2/src/use_web/gotion/tables/reorder
    GET    /mercariV2/src/use_web/gotion/tables/{table_id}
    PUT    /mercariV2/src/use_web/gotion/tables/{table_id}
    DELETE /mercariV2/src/use_web/gotion/tables/{table_id}
    GET    /mercariV2/src/use_web/gotion/tables/{table_id}/columns
    POST   /mercariV2/src/use_web/gotion/tables/{table_id}/columns
    PATCH  /mercariV2/src/use_web/gotion/tables/{table_id}/columns/reorder
    PUT    /mercariV2/src/use_web/gotion/tables/{table_id}/columns/{col_id}
    DELETE /mercariV2/src/use_web/gotion/tables/{table_id}/columns/{col_id}
    GET    /mercariV2/src/use_web/gotion/tables/{table_id}/rows
    POST   /mercariV2/src/use_web/gotion/tables/{table_id}/rows
    PUT    /mercariV2/src/use_web/gotion/tables/{table_id}/rows/{row_id}
    DELETE /mercariV2/src/use_web/gotion/tables/{table_id}/rows/{row_id}
    POST   /mercariV2/src/use_web/gotion/tables/{table_id}/import
"""

from fastapi import APIRouter

from .units.tables_handler import (
    list_tables,
    create_table,
    get_table,
    update_table,
    delete_table,
    reorder_tables,
    list_columns,
    create_column,
    update_column,
    delete_column,
    reorder_columns,
    list_rows,
    create_row,
    update_row,
    delete_row,
)
from .units.import_handler import import_from_file

router = APIRouter()

# Tables（/tables/reorder 须先于 /tables/{table_id} 注册，避免被路径参数吞掉）
router.add_api_route("/tables", list_tables, methods=["GET"])
router.add_api_route("/tables", create_table, methods=["POST"], status_code=201)
router.add_api_route("/tables/reorder", reorder_tables, methods=["PATCH"])
router.add_api_route("/tables/{table_id}", get_table, methods=["GET"])
router.add_api_route("/tables/{table_id}", update_table, methods=["PUT"])
router.add_api_route("/tables/{table_id}", delete_table, methods=["DELETE"], status_code=204)

# Columns
router.add_api_route("/tables/{table_id}/columns", list_columns, methods=["GET"])
router.add_api_route("/tables/{table_id}/columns", create_column, methods=["POST"], status_code=201)
router.add_api_route("/tables/{table_id}/columns/reorder", reorder_columns, methods=["PATCH"])
router.add_api_route("/tables/{table_id}/columns/{col_id}", update_column, methods=["PUT"])
router.add_api_route("/tables/{table_id}/columns/{col_id}", delete_column, methods=["DELETE"], status_code=204)

# Rows
router.add_api_route("/tables/{table_id}/rows", list_rows, methods=["GET"])
router.add_api_route("/tables/{table_id}/rows", create_row, methods=["POST"], status_code=201)
router.add_api_route("/tables/{table_id}/rows/{row_id}", update_row, methods=["PUT"])
router.add_api_route("/tables/{table_id}/rows/{row_id}", delete_row, methods=["DELETE"], status_code=204)

# Import
router.add_api_route("/tables/{table_id}/import", import_from_file, methods=["POST"])
