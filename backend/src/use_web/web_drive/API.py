# -*- coding: utf-8 -*-
"""WebDrive（Edge 子浏览器/出品自动化）API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/web_drive
- 完整 URL 示例: GET /mercariV2/src/use_web/web_drive/profiles-root
"""
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ...web_drive import get_web_drive_manager, profiles_root

router = APIRouter()
log = logging.getLogger(__name__)

# 出品进度轮询 job_id：仅允许安全字符（前端 crypto.randomUUID() 等）
_LISTING_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


class OpenSessionBody(PydanticModel):
    """启动指定账号的 Edge 子浏览器（独立 profile，Cookie 持久化在服务端目录）。"""

    account_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    headless: bool = False
    start_url: Optional[str] = None
    """有头交互会话默认从快照恢复标签；设为 false 且提供 start_url 时仅打开单页。"""
    restore_tabs: Optional[bool] = None
    use_mitm_proxy: bool = False
    mitm_proxy_url: Optional[str] = None


class CloseSessionBody(PydanticModel):
    account_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )


@router.get("/profiles-root")
def get_profiles_root():
    """返回当前 profile 根目录（环境变量 WEB_DRIVE_PROFILES_DIR 可覆盖）。"""
    return {"profiles_root": profiles_root()}


@router.get("/sessions")
async def list_sessions():
    return {"sessions": get_web_drive_manager().list_sessions()}


@router.post("/sessions/open")
async def open_session(body: OpenSessionBody):
    try:
        proxy = None
        if body.use_mitm_proxy:
            from ...ssl_mitm_proxy.runner import default_mitm_proxy_url

            proxy = (body.mitm_proxy_url or "").strip() or default_mitm_proxy_url()
        return {
            "success": True,
            "data": await get_web_drive_manager().open_session(
                body.account_key,
                headless=body.headless,
                start_url=body.start_url,
                proxy_server=proxy,
                interactive=not body.headless,
                restore_tabs=body.restore_tabs,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sessions/close")
async def close_session(body: CloseSessionBody):
    try:
        return {"success": True, "data": await get_web_drive_manager().close_session(body.account_key)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ──────────────────────── 出品自动化 ──────────────────────── #

class PostToMarketBody(PydanticModel):
    """出品自动化请求体（全字段）。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = ""
    description: str = ""
    image_urls: List[str] = []
    # 商品类型：mapping_id 用于从 DB 查出各级 position
    category_mapping_id: Optional[str] = None
    # 商品状態
    status: str = ""
    # 快递費負担：seller / buyer
    shipping_payer: str = "seller"
    # 配送方法：undecided / rakuraku / yuuyu / tanome / regular_mail
    shipping_method: str = "undecided"
    # 販売タイプ + 价格
    sale_type: str = "instant_buy"   # "instant_buy" | "auction"
    auction_duration: str = "normal"  # "normal" | "3hours"（仅 auction 时生效）
    price: int = 0
    # 发货
    shipping_days: str = "2_3_days"  # "1_2_days" | "2_3_days" | "4_7_days"
    shipping_from_area_id: str = ""  # Mercari area id，如 "13"
    # 代理
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True
    # 可选：与 GET /listing/post-progress/{job_id} 配合展示当前步骤
    progress_job_id: Optional[str] = Field(default=None, max_length=128)


def _get_category_positions(mapping_id: Optional[str]) -> dict:
    """根据 mapping_id 查询类别各级 position，找不到时返回全 None。"""
    if not mapping_id:
        return {}
    try:
        from ...db_manage.models.product_type_category_mapping import (
            ProductTypeCategoryMappingModel,
        )
        rows = ProductTypeCategoryMappingModel.find_all(
            where="mapping_id = ?",
            params=(str(mapping_id),),
            limit=1,
        )
        if not rows:
            return {}
        row = rows[0].to_dict()
        return {
            "category_level1_pos": row.get("category_level1_position"),
            "category_level2_pos": row.get("category_level2_position"),
            "category_level3_pos": row.get("category_level3_position"),
            "product_type_pos":    row.get("product_type_position"),
        }
    except Exception as exc:
        log.warning("查询 category positions 失败: %s", exc)
        return {}


@router.get("/listing/post-progress/{job_id}")
def listing_post_progress(job_id: str):
    """出品自动化执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    from ...web_drive.listing_progress import get_listing_progress

    jid = (job_id or "").strip()
    if not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_listing_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}


@router.post("/listing/post-to-market")
async def post_to_market(body: PostToMarketBody):
    """
    在独立有头 profile（``meilu_{id}__listing``，不复用系统预启动的 ``meilu_{id}`` 主窗口）
    经 SSL 中间人代理打开 https://jp.mercari.com/sell/create，并自动完成全部表单步骤：
      · Switch 检查 → 图片上传 → 商品名/说明填写
      · 商品类型选择 → 販売タイプ+价格 → 发货天数 → 发货地址
    """
    from ...web_drive.listing_progress import clear_listing_progress
    from ...web_drive.web_operate.post_to_macket import post_to_market as _do_post
    from ...ssl_mitm_proxy.runner import default_mitm_proxy_url

    jid = (body.progress_job_id or "").strip() or None
    if jid and not _LISTING_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        proxy: Optional[str] = None
        if body.use_mitm_proxy:
            proxy = (body.proxy_server or "").strip() or default_mitm_proxy_url()

        # 从 DB 查询 category position 字段
        cat_pos = _get_category_positions(body.category_mapping_id)

        data = await _do_post(
            get_web_drive_manager(),
            body.account_key,
            name=body.name,
            description=body.description,
            image_urls=body.image_urls,
            category_level1_pos=cat_pos.get("category_level1_pos"),
            category_level2_pos=cat_pos.get("category_level2_pos"),
            category_level3_pos=cat_pos.get("category_level3_pos"),
            product_type_pos=cat_pos.get("product_type_pos"),
            status=body.status,
            shipping_payer=body.shipping_payer,
            shipping_method=body.shipping_method,
            sale_type=body.sale_type,
            auction_duration=body.auction_duration,
            price=body.price,
            shipping_days=body.shipping_days,
            shipping_from_area_id=body.shipping_from_area_id,
            proxy_server=proxy,
            progress_job_id=jid,
        )
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("post_to_market 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if jid:
            clear_listing_progress(jid)


# ──────────────────────── 在售商品删除 ──────────────────────── #

class DeleteMercariItemBody(PydanticModel):
    """通过 WebDrive 在煤炉编辑页删除在售商品。"""

    account_key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    item_id: str = Field(..., min_length=1, max_length=64)
    proxy_server: Optional[str] = None
    use_mitm_proxy: bool = True


@router.post("/on-sale/delete-item")
async def delete_on_sale_item(body: DeleteMercariItemBody):
    """
    无头 MITM 浏览器（meilu_{id}__auto）打开编辑页删除商品，跳转出品一覧后同步本地列表，完成后自动关闭浏览器。
    """
    from ...web_drive.account_serial_queue import (
        queue_key_for_meilu_account,
        run_meilu_serial_async,
    )
    from ...web_drive.paths import meilu_id_from_account_key
    from ...web_drive.web_operate.delete_order import delete_mercari_item as _do_delete
    from ...ssl_mitm_proxy.runner import default_mitm_proxy_url

    item_id = (body.item_id or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id 不能为空")

    account_id = meilu_id_from_account_key(body.account_key)
    if account_id is None:
        raise HTTPException(status_code=400, detail="无效的 account_key")

    try:
        proxy: Optional[str] = None
        if body.use_mitm_proxy:
            proxy = (body.proxy_server or "").strip() or default_mitm_proxy_url()

        mgr = get_web_drive_manager()

        async def _run() -> Dict[str, Any]:
            return await _do_delete(
                mgr,
                body.account_key,
                item_id=item_id,
                proxy_server=proxy,
            )

        data = await run_meilu_serial_async(
            queue_key_for_meilu_account(account_id),
            _run,
        )
        return {"success": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("delete_on_sale_item 异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
