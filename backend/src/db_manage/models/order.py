# -*- coding: utf-8 -*-
"""
订单表模型。

SQLite：`order_date`、`order_updated_at`、`purchase_time` 均为 INTEGER，存 Mercari 原始 Unix 秒；
`amount`、`service_fee`、`net_income`、`shipping_fee` 为 INTEGER，存日元整数；
展示与时区换算由前端完成。
"""

from typing import Any, Dict, List, Optional, Tuple
from ..base_model import BaseModel
from .order_outbound_line import TERMINAL_ORDER_STATUSES


class OrderModel(BaseModel):
    """订单表"""

    @classmethod
    def ensure_table_exists(cls) -> bool:
        ok = super().ensure_table_exists()
        if ok and hasattr(cls, "_cached_table_columns"):
            delattr(cls, "_cached_table_columns")
        return ok

    @classmethod
    def get_table_name(cls) -> str:
        return "orders"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'order_no': {
                'type': 'TEXT',
                'not_null': True,
                'unique': True,
                'default': None,
            },
            # Mercari 原始 Unix 时间戳（秒），前端按本地时区展示
            'order_date': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
            'order_updated_at': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'purchase_time': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 买家用户 ID（Mercari buyer.id），非昵称
            'customer_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 卖家用户 ID（Mercari seller.id）。故意不设 NOT NULL：SQLite 改约束需重建表，维持可空即可。
            'data_user': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'status': {
                'type': 'TEXT',
                'not_null': True,
                'default': "'pending'",
            },
            'amount': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'service_fee': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'net_income': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 快递公司（items/get shipping_class.carrier_display_name）
            'carrier_display_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 寄件方式展示名（items/get shipping_class.request_class_display_name）
            'request_class_display_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'shipping_fee': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 快递单号
            'tracking_no': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # items/get data.transaction_evidence.id
            'transaction_evidence_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'remark': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # transaction_evidences/get data.description（商品说明）
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 是否已执行过“刷新后同步库存扣减”：0=未同步，1=已同步（防重复扣减）
            'inventory_synced': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 本订单已同步扣减的库存总数量（首次同步写入）
            'inventory_synced_quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # Mercari item.thumbnails：JSON 字符串，如 ["https://..."]
            'thumbnails': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_orders_order_no', 'columns': ['order_no'], 'unique': True},
            {'name': 'idx_orders_order_date', 'columns': ['order_date']},
            {'name': 'idx_orders_order_updated_at', 'columns': ['order_updated_at']},
            {'name': 'idx_orders_status', 'columns': ['status']},
        ]

    @classmethod
    def _build_list_filter(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> Tuple[str, List[Any]]:
        base_sql = """
            FROM [orders] o
            WHERE 1=1
        """
        params: List[Any] = []
        if keyword:
            base_sql += (
                " AND (o.order_no LIKE ? OR o.customer_name LIKE ? "
                "OR IFNULL(o.data_user, '') LIKE ? "
                "OR IFNULL(o.remark, '') LIKE ? "
                "OR IFNULL(o.description, '') LIKE ?)"
            )
            kw = f"%{keyword}%"
            params += [kw, kw, kw, kw, kw]
        if status:
            base_sql += " AND o.status = ?"
            params.append(status)
        if start_ts is not None:
            base_sql += (
                " AND COALESCE(o.purchase_time, o.order_date) >= ?"
            )
            params.append(int(start_ts))
        if end_ts is not None:
            base_sql += (
                " AND COALESCE(o.purchase_time, o.order_date) <= ?"
            )
            params.append(int(end_ts))
        return base_sql, params

    @classmethod
    def aggregate_sums(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        与列表相同的筛选条件下，对全量匹配行求和（非当前页）。

        统计口径：status=cancelled 的订单不计入 total_count / sum_amount /
        sum_service_fee / sum_shipping_fee / sum_net_income（与列表筛选无关，列表仍可只看已取消）。
        """
        db = cls().db
        base_sql, params = cls._build_list_filter(
            keyword=keyword, status=status, start_ts=start_ts, end_ts=end_ts
        )
        base_sql += " AND o.status != 'cancelled'"
        sql = f"""
            SELECT
                COUNT(*),
                COALESCE(SUM(o.amount), 0),
                COALESCE(SUM(o.service_fee), 0),
                COALESCE(SUM(o.shipping_fee), 0),
                COALESCE(SUM(o.net_income), 0)
            {base_sql}
        """
        row = db.execute_query(sql, tuple(params))[0]
        return {
            "total_count": int(row[0]),
            "sum_amount": int(row[1]),
            "sum_service_fee": int(row[2]),
            "sum_shipping_fee": int(row[3]),
            "sum_net_income": int(row[4]),
        }

    # items/get 批量刷新时排除：已完成(done)、取消、历史売切（煤炉侧终态）
    _STATUSES_SKIP_BATCH_INFO: Tuple[str, ...] = (
        "done",
        "cancelled",
        "sold_out",
    )

    @classmethod
    def find_for_batch_info_refresh(
        cls,
        seller_id_filter: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """
        从库中取得待用 transaction_evidences/get 刷新的 (order_no, data_user)。
        仅含 data_user 非空且状态非「已完成」集合中的行；可选只限某一卖家（与煤炉账号 seller_id 一致）。
        """
        skip = cls._STATUSES_SKIP_BATCH_INFO
        placeholders = ",".join("?" * len(skip))
        sql = (
            f"SELECT order_no, data_user FROM [{cls.get_table_name()}] "
            f"WHERE IFNULL(TRIM(data_user), '') != '' "
            f"AND status NOT IN ({placeholders}) "
        )
        params: List[Any] = list(skip)
        if seller_id_filter is not None and str(seller_id_filter).strip():
            sql += "AND TRIM(data_user) = TRIM(?) "
            params.append(str(seller_id_filter).strip())
        sql += (
            "ORDER BY COALESCE(purchase_time, order_updated_at, order_date) DESC, "
            "id DESC"
        )
        db = cls().db
        rows = db.execute_query(sql, tuple(params))
        out: List[Tuple[str, str]] = []
        for r in rows:
            if not r or len(r) < 2:
                continue
            ono, du = r[0], r[1]
            if ono is None or str(ono).strip() == "":
                continue
            out.append((str(ono).strip(), str(du).strip()))
        return out

    @classmethod
    def find_detail_list(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        db = cls().db
        base_sql, params = cls._build_list_filter(
            keyword=keyword, status=status, start_ts=start_ts, end_ts=end_ts
        )

        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]
        term_ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
        pending_sql = f"""
            COALESCE((
                SELECT SUM(COALESCE(l.[quantity], 1))
                FROM [order_outbound_lines] l
                WHERE l.[order_no] = o.[order_no]
                  AND COALESCE(l.[is_stocked_out], 0) = 0
            ), 0)
        """
        pending_case_sql = f"""
            CASE
                WHEN o.[status] IN ({term_ph}) THEN 0
                ELSE ({pending_sql})
            END
        """
        select_sql = f"""
            SELECT o.id, o.order_no, o.order_date, o.order_updated_at, o.purchase_time, o.customer_name, o.data_user,
                   o.status, o.amount,
                   o.service_fee, o.net_income, o.carrier_display_name, o.request_class_display_name,
                   o.shipping_fee, o.tracking_no, o.transaction_evidence_id, o.remark, o.description,
                   o.inventory_synced, o.inventory_synced_quantity, o.thumbnails,
                   {pending_case_sql} AS pending_outbound_qty
            {base_sql}
            ORDER BY COALESCE(o.purchase_time, o.order_updated_at, o.order_date) DESC, o.id DESC
            LIMIT ? OFFSET ?
        """
        bind = tuple(TERMINAL_ORDER_STATUSES) + tuple(params) + (page_size, (page - 1) * page_size)
        rows = db.execute_query(select_sql, bind)
        keys = [
            'id', 'order_no', 'order_date', 'order_updated_at', 'purchase_time', 'customer_name', 'data_user', 'status',
            'amount',
            'service_fee', 'net_income', 'carrier_display_name', 'request_class_display_name',
            'shipping_fee', 'tracking_no', 'transaction_evidence_id', 'remark', 'description',
            'inventory_synced', 'inventory_synced_quantity', 'thumbnails', 'pending_outbound_qty',
        ]
        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': [dict(zip(keys, row)) for row in rows],
        }
