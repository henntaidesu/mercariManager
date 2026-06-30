# -*- coding: utf-8 -*-
"""留言（Comment 通知）相关 API 请求体（Pydantic）。"""
from typing import Optional

from pydantic import BaseModel as PydanticModel


class ItemCommentSyncRequest(PydanticModel):
    item_id: str
    account_id: Optional[int] = None
    progress_job_id: Optional[str] = None


class ItemCommentPostRequest(PydanticModel):
    item_id: str
    message: str
    account_id: Optional[int] = None
    progress_job_id: Optional[str] = None


class ItemCommentCloseRequest(PydanticModel):
    account_id: Optional[int] = None


class ItemCommentTranslateRequest(PydanticModel):
    text: str
