# -*- coding: utf-8 -*-
"""应用配置：出品默认值等（存于 [config] 表）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/app_config
- 完整 URL 示例: GET /mercariV2/src/use_web/app_config/<endpoint>
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from ...db_manage.models.config_entry import ConfigEntryModel
from ...db_manage.models.meilu_account import MeiluAccountModel

router = APIRouter()

_K_SHIP_FROM = "listing_defaults_shipping_from_area_id"
_K_SHIP_METHOD = "listing_defaults_shipping_method"
_K_SHIP_PAYER = "listing_defaults_shipping_payer"
_K_SHIP_DAYS = "listing_defaults_shipping_days"
_K_MEILU = "listing_defaults_meilu_account_id"

_ALLOWED_METHODS = frozenset({"undecided", "rakuraku", "yuuyu", "tanome", "regular_mail"})
_ALLOWED_PAYERS = frozenset({"seller", "buyer"})
_ALLOWED_DAYS = frozenset({"1_2_days", "2_3_days", "4_7_days"})


class ListingDefaultsOut(BaseModel):
    """与库存页出品表单字段对齐（发货地为煤炉 area id 字符串）。"""

    shipping_from_area_id: Optional[str] = None
    shipping_method: Optional[str] = None
    shipping_payer: Optional[str] = None
    shipping_days: Optional[str] = None
    meilu_account_id: Optional[int] = None


class ListingDefaultsUpdate(BaseModel):
    shipping_from_area_id: Optional[str] = Field(default=None, max_length=8)
    shipping_method: Optional[str] = None
    shipping_payer: Optional[str] = None
    shipping_days: Optional[str] = None
    meilu_account_id: Optional[int] = None

    @field_validator("shipping_from_area_id", mode="before")
    @classmethod
    def strip_area(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("shipping_method", "shipping_payer", "shipping_days", mode="before")
    @classmethod
    def strip_opt(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


def _read_listing_defaults() -> Dict[str, Any]:
    raw_area = ConfigEntryModel.get_value(_K_SHIP_FROM)
    raw_method = ConfigEntryModel.get_value(_K_SHIP_METHOD)
    raw_payer = ConfigEntryModel.get_value(_K_SHIP_PAYER)
    raw_days = ConfigEntryModel.get_value(_K_SHIP_DAYS)
    raw_meilu = ConfigEntryModel.get_value(_K_MEILU)
    mid: Optional[int] = None
    if raw_meilu:
        try:
            mid = int(str(raw_meilu).strip())
            if mid <= 0:
                mid = None
        except ValueError:
            mid = None
    return {
        "shipping_from_area_id": raw_area,
        "shipping_method": raw_method,
        "shipping_payer": raw_payer,
        "shipping_days": raw_days,
        "meilu_account_id": mid,
    }


@router.get("/listing-defaults", response_model=ListingDefaultsOut)
def get_listing_defaults():
    return ListingDefaultsOut(**_read_listing_defaults())


@router.put("/listing-defaults", response_model=ListingDefaultsOut)
def put_listing_defaults(body: ListingDefaultsUpdate):
    data = body.model_dump(exclude_unset=True)

    if "shipping_method" in data:
        v = data["shipping_method"]
        if v is not None and v not in _ALLOWED_METHODS:
            raise HTTPException(status_code=400, detail=f"无效的 shipping_method: {v}")

    if "shipping_payer" in data:
        v = data["shipping_payer"]
        if v is not None and v not in _ALLOWED_PAYERS:
            raise HTTPException(status_code=400, detail=f"无效的 shipping_payer: {v}")

    if "shipping_days" in data:
        v = data["shipping_days"]
        if v is not None and v not in _ALLOWED_DAYS:
            raise HTTPException(status_code=400, detail=f"无效的 shipping_days: {v}")

    if "meilu_account_id" in data:
        mid = data["meilu_account_id"]
        if mid is not None:
            if mid <= 0:
                raise HTTPException(status_code=400, detail="meilu_account_id 须为正整数")
            found = MeiluAccountModel.find_all("[id] = ?", (mid,), limit=1)
            if not found:
                raise HTTPException(status_code=400, detail=f"煤炉账号不存在: id={mid}")

    if "shipping_from_area_id" in data:
        ConfigEntryModel.set_value(_K_SHIP_FROM, data["shipping_from_area_id"])
    if "shipping_method" in data:
        ConfigEntryModel.set_value(_K_SHIP_METHOD, data["shipping_method"])
    if "shipping_payer" in data:
        ConfigEntryModel.set_value(_K_SHIP_PAYER, data["shipping_payer"])
    if "shipping_days" in data:
        ConfigEntryModel.set_value(_K_SHIP_DAYS, data["shipping_days"])
    if "meilu_account_id" in data:
        mid = data["meilu_account_id"]
        ConfigEntryModel.set_value(_K_MEILU, str(mid) if mid is not None else None)

    return ListingDefaultsOut(**_read_listing_defaults())
