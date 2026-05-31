# -*- coding: utf-8 -*-
"""待办事项 API 请求体（Pydantic）。"""
from typing import Optional

from pydantic import BaseModel as PydanticModel, Field


class SyncTodosRequest(PydanticModel):
    account_id: Optional[int] = None
    progress_job_id: Optional[str] = None


class SendTransactionMessageRequest(PydanticModel):
    text: str = Field(..., min_length=1, max_length=2000)
    progress_job_id: Optional[str] = None


class ConfirmShippingSelectionRequest(PydanticModel):
    class_text: str = Field(..., min_length=1, max_length=200)
    # 仅对需要选择 facility 的 size 必填，与煤炉 radio value 一致：
    # 'POST_OFFICE' | 'LAWSON' | 'SEVEN_ELEVEN' | 'FAMILY_MART' | 'YAMATO_OFFICE' | 'PUDO' | None
    facility: Optional[str] = None
    # ゆうパケットポスト/mini：完了後そのまま「2次元コードを読み取る」を押して QR スキャナを開く
    scan_qr: bool = False
    # 需选发货地的方法（ゆうパケットポスト系以外）：完了後、返回交易ページ发行 发送用 QR/条形码（无需摄像头）
    generate_code: bool = False
    progress_job_id: Optional[str] = None


class ChangeShippingMethodRequest(PydanticModel):
    """在 /shipping_method 页选中配送方式并点「変更する」。

    ``method_value`` 为 radio 的 value（优先），``method_label`` 为可读标签（回落）。
    """

    method_value: str = ""
    method_label: str = ""
    progress_job_id: Optional[str] = None


class CameraFrameRequest(PydanticModel):
    """客户端摄像头单帧（data URL）→ 推送到有头浏览器的虚拟摄像头。

    ``frame`` 为空时仅查询扫描状态（done/on_scanner），不写入画面。
    """

    frame: str = ""
    width: int = 0
    height: int = 0


class SubmitTransactionReviewRequest(PydanticModel):
    text: str = Field(..., min_length=1, max_length=140)
    progress_job_id: Optional[str] = None


class TransactionActionRequest(PydanticModel):
    """无 body 的浏览器操作（拉详情/启动尺寸选择/修改发送方式）仍需透传 job_id。"""

    progress_job_id: Optional[str] = None


class SendMessageReactionRequest(PydanticModel):
    """对买家某条消息发送 emoji 反应。

    ``reaction_index`` 必填：前端按 ``messages.filter(is_buyer=true).indexOf(target)`` 计算，
    后端用其在 DOM 上定位第 N 个 ``[data-testid="add-reaction-button"]``。
    """

    # 仅用于日志/审计；后端不会用它在 DOM 里查找
    message_id: Optional[str] = None
    reaction_index: int = Field(..., ge=0)
    # emoji 关键字（thumbsup/heart/smile/pray/cry/clap/sparkles/ok 等）
    reaction: str = Field(..., min_length=1, max_length=32)
    progress_job_id: Optional[str] = None
