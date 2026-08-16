# -*- coding: utf-8 -*-
"""一键修改发货时效端点（系统配置页）。

GET 只算件数（纯 SQL，随筛选条件即时刷新）；POST 把整批修改交给任务队列的
``system.shipping_duration`` 单条任务，进度看 /#/tasks。

同一个 POST 兼作「重试」：批量执行中途失败后再提交一次相同参数即可只处理剩余商品
（``bulk_shipping_duration.run`` 每次按当前 ``shipping_duration_id`` 重算目标集合）。
"""
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ....auth import require_auth
from ....bulk_shipping_duration import preview
from ....task_queue import TaskDuplicateError, submit_task
from ....task_queue.registry import SYSTEM_SHIPPING_DURATION


class ShippingDurationPreviewOut(BaseModel):
    """范围内的件数；``task_id`` 仅在 POST 时返回本次提交的任务。"""

    target: str
    target_name: str
    #: 待修改（时效 ≠ 目标，含从未同步过详情、时效为空的行）
    pending: int
    #: 已经是目标时效、本次不会碰的件数
    already: int
    total: int
    task_id: Optional[int] = None


class ShippingDurationUpdate(BaseModel):
    #: 煤炉「発送までの日数」option value：1=1~2日 / 2=2~3日 / 3=4~7日（雅虎侧自动映射）
    target: str = Field(..., max_length=8)
    #: 留空 = 全部账号
    account_id: Optional[int] = None
    #: 留空 = 全部平台；mercari / yahoo
    platform: Optional[str] = Field(default=None, max_length=16)


def get_shipping_duration(
    target: str = Query(..., max_length=8),
    account_id: Optional[int] = Query(default=None),
    platform: Optional[str] = Query(default=None, max_length=16),
):
    try:
        return ShippingDurationPreviewOut(
            **preview(target, account_id=account_id, platform=platform)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def post_shipping_duration(
    body: ShippingDurationUpdate, claims: dict = Depends(require_auth)
):
    """提交整批修改任务。件数为 0 时不入队，直接把当前统计回给前端。"""
    try:
        stats = preview(body.target, account_id=body.account_id, platform=body.platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not stats["pending"]:
        return ShippingDurationPreviewOut(**stats)

    try:
        task, _created = submit_task(
            task_type=SYSTEM_SHIPPING_DURATION,
            payload={
                "target": stats["target"],
                "account_id": body.account_id,
                "platform": (body.platform or "").strip().lower() or None,
            },
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except TaskDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ShippingDurationPreviewOut(**stats, task_id=int(task["id"]))
