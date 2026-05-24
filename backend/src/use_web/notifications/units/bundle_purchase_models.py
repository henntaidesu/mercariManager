# -*- coding: utf-8 -*-
"""合并购买请求 API 请求体（Pydantic）。"""
from typing import Optional

from pydantic import BaseModel as PydanticModel


class BundlePurchaseSyncRequest(PydanticModel):
    bundle_id: str
    account_id: Optional[int] = None
    notification_id: Optional[int] = None


class BundlePurchaseDecideRequest(PydanticModel):
    """承诺 / 拒绝合并购买请求。

    - ``action='accept'`` 时必须携带 4 个 shipping_* 字段(填入表单后点「依頼を承諾する」)
    - ``action='reject'`` 时忽略表单字段,直接点「依頼を断る」

    字段语义：
    - shipping_payer: seller(送料込み) / buyer(着払い)
    - shipping_method: undecided / rakuraku / yuuyu / takunomeru / yumail /
      letter_pack / postal / kuroneko / yupack / clickpost / yupacket
    - shipping_from: 行政区 id(与 inventory 出品表单一致)
    - shipping_days: 1_2_days / 2_3_days / 4_7_days
    """

    action: str
    account_id: Optional[int] = None
    shipping_payer: Optional[str] = None
    shipping_method: Optional[str] = None
    shipping_from: Optional[str] = None
    shipping_days: Optional[str] = None
