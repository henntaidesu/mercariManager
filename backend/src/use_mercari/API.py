# -*- coding: utf-8 -*-
"""
Mercari 操作相关 API 路由

层级蓝图注册：
- 从 src/API.py 接收前缀 /mercariV2/src
- 完整 URL 格式: /mercariV2/src/use_mercari/<endpoint>
"""

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel as PydanticModel

from ..web_drive.core.account_serial_queue import (
    GLOBAL_QUEUE_KEY,
    queue_key_for_mercari_account,
    resolve_mercari_account_id,
    run_mercari_serial_async,
)
from ..web_drive.core.manager import get_web_drive_manager
from ..web_drive.core.paths import mercari_account_key
from .sync_data import (
    batch_refresh_orders_info,
    history_sync_precheck,
    resolve_enabled_account_ids,
    sync_new_data,
    sync_open_orders,
)
from .sync_progress import (
    clear_sync_progress,
    get_sync_progress,
)
from .sync_lock import (
    LABEL_FULL,
    begin_or_conflict as sync_lock_begin,
    end as sync_lock_end,
    status as sync_lock_status,
)

router = APIRouter(prefix="/use_mercari", tags=["use-mercari"])

log = logging.getLogger(__name__)

# 与 listing_post_progress 相同的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


class SyncOrdersRequest(PydanticModel):
    account_id: Optional[int] = None
    progress_job_id: Optional[str] = None


@router.post("/sync-new-data")
async def api_sync_new_data(data: SyncOrdersRequest):
    """
    订单页「更新列表」：对所有已开启账号（status=active 且 is_open=1）逐个串行执行——
    WebDriver 打开取引中一覧 + MITM 截获 trading 列表；仅增量入库尚未存在的出售中单，倒序写入。

    不再指定单个账号：点击即更新全部已开启账号，逐个执行并汇总结果；每账号完成后立即关闭其浏览器。
    """
    jid = (data.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        account_ids = resolve_enabled_account_ids()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lock_token = sync_lock_begin("page", LABEL_FULL)
    accounts: List[Dict[str, Any]] = []
    api_item_count = pending_new = inserted = info_enriched = 0
    fail_count = 0
    mgr = get_web_drive_manager()
    try:
        for aid in account_ids:
            try:
                stats = await run_mercari_serial_async(
                    queue_key_for_mercari_account(aid),
                    lambda aid=aid: sync_new_data(account_id=aid, progress_job_id=jid),
                )
            except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
                fail_count += 1
                accounts.append({"account_id": aid, "error": str(exc)})
                continue
            else:
                api_item_count += int(stats.get("api_item_count", 0) or 0)
                pending_new += int(stats.get("pending_new", 0) or 0)
                inserted += int(stats.get("inserted", 0) or 0)
                info_enriched += int(stats.get("info_enriched", 0) or 0)
                accounts.append(stats)
            finally:
                # 关闭当前账号浏览器，确保与下一账号不重叠（队列层默认 ~10s 后才关）。
                try:
                    await mgr.close_session(mercari_account_key(aid), force=True)
                except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                    log.warning(
                        "[orders] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                    )
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_sync_progress(jid)

    return {
        "success": True,
        "data": {
            "accounts": accounts,
            "account_count": len(account_ids),
            "fail_count": fail_count,
            "api_item_count": api_item_count,
            "pending_new": pending_new,
            "inserted": inserted,
            "info_enriched": info_enriched,
        },
    }


@router.post("/batch-refresh-info")
async def api_batch_refresh_info(data: SyncOrdersRequest):
    """
    订单页「更新状态」：逐条打开取引页并由 MITM 截获 transaction_evidences/get 回填（与单行刷新一致）。
    account_id：可选；指定则只处理该账号 seller_id 对应的订单。
    """
    jid = (data.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")
    lock_token = sync_lock_begin("page", LABEL_FULL)
    try:
        if data.account_id is not None:
            qk = queue_key_for_mercari_account(int(data.account_id))
            result = await run_mercari_serial_async(
                qk,
                lambda: batch_refresh_orders_info(
                    account_id=int(data.account_id),
                    progress_job_id=jid,
                ),
            )
        else:
            result = await run_mercari_serial_async(
                GLOBAL_QUEUE_KEY,
                lambda: batch_refresh_orders_info(
                    account_id=None,
                    progress_job_id=jid,
                ),
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"批量刷新失败: {exc}") from exc
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_sync_progress(jid)

    return {"success": True, "data": result}


@router.get("/sync-lock")
def api_sync_lock_status():
    """全局同步锁状态：是否有同步在进行及其类型，供前端轮询禁用同步按钮。"""
    return {"success": True, "data": sync_lock_status()}


@router.get("/sync-progress/{job_id}")
def api_orders_sync_progress(job_id: str):
    """更新列表 / 更新状态执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}


@router.get("/history-sync-precheck")
def api_history_sync_precheck(account_id: Optional[int] = Query(None)):
    """
    「获取历史数据」前置校验：若 orders 中已有 data_user = 该账号卖家 ID 的数据，返回 allowed=false。
    """
    try:
        data = history_sync_precheck(account_id=account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"校验失败: {exc}") from exc
    return {"success": True, "data": data}


@router.post("/sync-orders")
async def sync_orders(data: SyncOrdersRequest):
    """
    触发 Mercari 订单同步（出售中 trading + 已售完 sold_out 历史），写入同一订单表。

    - account_id: 指定煤炉账号 ID，不传则自动选取第一个 active 账号。
    - 卖家ID: 从煤炉账号配置中读取（不再由接口传入）。
    """
    try:
        aid = resolve_mercari_account_id(data.account_id)
        result = await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: sync_open_orders(account_id=aid),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步失败: {exc}") from exc

    return {"success": True, "data": result}
