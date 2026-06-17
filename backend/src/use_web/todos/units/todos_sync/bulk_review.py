# -*- coding: utf-8 -*-
"""一键好评批量提交端点：按账号分组，每账号在串行队列内复用一个浏览器逐条评价。"""

import logging
from typing import Any, Dict, List
from fastapi import HTTPException
from .....use_mercari.get_to_du_list.transaction_detail import (
    bulk_submit_reviews_for_account,
    pending_review_account_ids,
)
from .....use_mercari.sync.sync_progress import clear_sync_progress, set_sync_progress
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from ..todos_models import BulkSubmitReviewsRequest
from .detail import _validate_job_id

log = logging.getLogger(__name__)


async def bulk_submit_reviews_endpoint(req: BulkSubmitReviewsRequest) -> Dict[str, Any]:
    """对所有启用账号下「評価をしてください」待办批量提交好评。

    与「从煤炉同步」一致逐账号严格串行：每个账号作为一个队列任务
    （``suppress_idle_close=True`` 复用同一 ``__todo`` 浏览器会话），账号内逐条评价后
    在该任务末尾统一关闭浏览器，再开始下一个账号。``progress_job_id`` 与
    GET /use_web/todos/sync-progress/{job_id} 配合供前端轮询。
    """
    jid = _validate_job_id(req.progress_job_id)
    text = (req.text or "").strip()

    account_ids = pending_review_account_ids()
    if not account_ids:
        if jid:
            clear_sync_progress(jid)
        return {"account_count": 0, "ok": 0, "fail": 0, "total": 0, "accounts": [], "failures": []}

    accounts: List[Dict[str, Any]] = []
    ok = fail = total = 0
    failures: List[str] = []
    try:
        for i, aid in enumerate(account_ids, start=1):
            prefix = f"账号 {i}/{len(account_ids)}"
            if jid:
                set_sync_progress(jid, "bulk_review_account", f"{prefix} 开始一键好评…")
            try:
                stats = await run_mercari_serial_async(
                    queue_key_for_mercari_account(aid),
                    lambda aid=aid, prefix=prefix: bulk_submit_reviews_for_account(
                        aid, text, progress_job_id=jid, progress_prefix=prefix
                    ),
                    suppress_idle_close=True,
                )
            except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
                fail += 1
                failures.append(f"账号#{aid}: {exc}")
                accounts.append({"account_id": aid, "error": str(exc)})
                log.warning("[bulk_review] account_id=%s 整体失败: %s", aid, exc)
                continue
            ok += int(stats.get("ok", 0) or 0)
            fail += int(stats.get("fail", 0) or 0)
            total += int(stats.get("total", 0) or 0)
            failures.extend(stats.get("failures") or [])
            accounts.append(stats)
    finally:
        if jid:
            clear_sync_progress(jid)

    return {
        "account_count": len(account_ids),
        "ok": ok,
        "fail": fail,
        "total": total,
        "accounts": accounts,
        "failures": failures,
    }
