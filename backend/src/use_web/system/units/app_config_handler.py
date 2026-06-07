# -*- coding: utf-8 -*-
"""应用配置处理器：出品默认值读写 + 自动出品总开关。"""

from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from ....db_manage.models.config_entry import ConfigEntryModel
from ....db_manage.models.mercari_account import MercariAccountModel

_K_SHIP_FROM = "listing_defaults_shipping_from_area_id"
_K_SHIP_METHOD = "listing_defaults_shipping_method"
_K_SHIP_PAYER = "listing_defaults_shipping_payer"
_K_SHIP_DAYS = "listing_defaults_shipping_days"
_K_MERCARI = "listing_defaults_mercari_account_id"
_K_CONDITION = "listing_defaults_condition"
_K_SALE_TYPE = "listing_defaults_sale_type"

_ALLOWED_METHODS = frozenset({"undecided", "rakuraku", "yuuyu", "tanome", "regular_mail"})
_ALLOWED_PAYERS = frozenset({"seller", "buyer"})
_ALLOWED_DAYS = frozenset({"1_2_days", "2_3_days", "4_7_days"})
_ALLOWED_CONDITIONS = frozenset({"new_unused", "almost_unused", "good", "fair", "used"})
_ALLOWED_SALE_TYPES = frozenset({"instant_buy", "auction"})


class ListingDefaultsOut(BaseModel):
    """与库存页出品表单字段对齐（发货地为煤炉 area id 字符串）。"""

    shipping_from_area_id: Optional[str] = None
    shipping_method: Optional[str] = None
    shipping_payer: Optional[str] = None
    shipping_days: Optional[str] = None
    mercari_account_id: Optional[int] = None
    # 自动出品兜底用（库存不存这两个字段）：商品状态 / 售卖类型
    condition: Optional[str] = None
    sale_type: Optional[str] = None


class ListingDefaultsUpdate(BaseModel):
    shipping_from_area_id: Optional[str] = Field(default=None, max_length=8)
    shipping_method: Optional[str] = None
    shipping_payer: Optional[str] = None
    shipping_days: Optional[str] = None
    mercari_account_id: Optional[int] = None
    condition: Optional[str] = None
    sale_type: Optional[str] = None

    @field_validator("shipping_from_area_id", mode="before")
    @classmethod
    def strip_area(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator(
        "shipping_method", "shipping_payer", "shipping_days", "condition", "sale_type",
        mode="before",
    )
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
    raw_mercari = ConfigEntryModel.get_value(_K_MERCARI)
    raw_condition = ConfigEntryModel.get_value(_K_CONDITION)
    raw_sale_type = ConfigEntryModel.get_value(_K_SALE_TYPE)
    mid: Optional[int] = None
    if raw_mercari:
        try:
            mid = int(str(raw_mercari).strip())
            if mid <= 0:
                mid = None
        except ValueError:
            mid = None
    return {
        "shipping_from_area_id": raw_area,
        "shipping_method": raw_method,
        "shipping_payer": raw_payer,
        "shipping_days": raw_days,
        "mercari_account_id": mid,
        "condition": raw_condition,
        "sale_type": raw_sale_type,
    }


class MgmtCipherModeOut(BaseModel):
    """管理番号暗号编码模式：'binary'（二进制 ◇◆）/ 'base5'（五进制 -=~<>）。"""

    mode: str


class MgmtCipherModeUpdate(BaseModel):
    mode: str


def get_mgmt_cipher_mode():
    from ....use_mercari.mgmt_id_cipher import get_cipher_mode

    return MgmtCipherModeOut(mode=get_cipher_mode())


def put_mgmt_cipher_mode(body: MgmtCipherModeUpdate):
    mode = (body.mode or "").strip().lower()
    if mode not in ("binary", "base5"):
        raise HTTPException(status_code=400, detail=f"无效的 mode: {body.mode}")
    from ....use_mercari.mgmt_id_cipher import MGMT_CIPHER_MODE_KEY

    # base5 为默认：存空即删除该键；binary 显式写入
    ConfigEntryModel.set_value(MGMT_CIPHER_MODE_KEY, "binary" if mode == "binary" else None)
    return MgmtCipherModeOut(mode=mode)


def get_listing_defaults():
    return ListingDefaultsOut(**_read_listing_defaults())


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

    if "condition" in data:
        v = data["condition"]
        if v is not None and v not in _ALLOWED_CONDITIONS:
            raise HTTPException(status_code=400, detail=f"无效的 condition: {v}")

    if "sale_type" in data:
        v = data["sale_type"]
        if v is not None and v not in _ALLOWED_SALE_TYPES:
            raise HTTPException(status_code=400, detail=f"无效的 sale_type: {v}")

    if "mercari_account_id" in data:
        mid = data["mercari_account_id"]
        if mid is not None:
            if mid <= 0:
                raise HTTPException(status_code=400, detail="mercari_account_id 须为正整数")
            found = MercariAccountModel.find_all("[id] = ?", (mid,), limit=1)
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
    if "condition" in data:
        ConfigEntryModel.set_value(_K_CONDITION, data["condition"])
    if "sale_type" in data:
        ConfigEntryModel.set_value(_K_SALE_TYPE, data["sale_type"])
    if "mercari_account_id" in data:
        mid = data["mercari_account_id"]
        ConfigEntryModel.set_value(_K_MERCARI, str(mid) if mid is not None else None)

    return ListingDefaultsOut(**_read_listing_defaults())
