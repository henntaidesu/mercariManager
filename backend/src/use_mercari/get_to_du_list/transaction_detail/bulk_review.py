# -*- coding: utf-8 -*-
"""一键好评：批量提交取引評価。

设计要点（与 ``precache_uncached_todo_details`` 同范式）：
- 按账号分组，**每个账号在自己的串行队列内**复用同一个 ``__todo`` 浏览器会话，
  逐条导航 → 评价 → 软删，全部完成后**统一关闭一次**浏览器。
- 不在评价热路径里做订单财务回填（``apply_item_info_to_order`` 的 90s MITM 抓取），
  批量场景交由常规订单同步链路补齐，避免逐条阻塞与浏览器残留。
- 单条失败仅记录、不抛出，不影响该账号其余条目；账号登录态失效则该账号剩余全部计失败。

跨账号的循环与串行队列包装放在路由层（见 use_web/todos），本模块只提供
``bulk_submit_reviews_for_account``（**必须在该账号串行队列内调用**）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ....db_manage.models.todo_item import TodoItemModel
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.mitm_session import MercariLoginRequiredError, mitm_automation_browser
from ....web_drive.core.paths import mercari_automation_key, mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ...sync.sync_progress import make_sync_reporter
from .review import DEFAULT_REVIEW_TEXT, _soft_delete_review_todo, drive_review_on_page

log = logging.getLogger(__name__)

# 批量财务回填单条 MITM 截获上限（秒）：限制最坏耗时，失败由常规订单同步补齐
_REFRESH_TIMEOUT_SEC = 30


async def _refresh_orders_after_reviews(
    account_id: int,
    item_ids: List[str],
    report: Any,
    progress_prefix: str,
) -> None:
    """评价完成后回填订单财务字段：复用同一 ``__sync`` 浏览器逐条截获 transaction_evidences，
    结束统一关闭。单条失败仅记录，不影响评价结果（订单同步链路会再补齐）。"""
    if not item_ids:
        return
    mgr = get_web_drive_manager()
    sync_key = mercari_automation_key(int(account_id))
    n = len(item_ids)
    try:
        for idx, item_id in enumerate(item_ids, start=1):
            report("bulk_review_refresh", f"{progress_prefix} 刷新订单（{idx}/{n}）{item_id}…")
            try:
                err = await apply_item_info_to_order(
                    item_id, account_id=int(account_id), timeout=_REFRESH_TIMEOUT_SEC
                )
                if err:
                    log.warning("[bulk_review] 订单刷新返回错误 item_id=%s: %s", item_id, err)
            except Exception as exc:  # noqa: BLE001 单条刷新失败不阻断其余
                log.warning("[bulk_review] 订单刷新异常 item_id=%s: %s", item_id, exc)
    finally:
        try:
            await mgr.close_session(sync_key, force=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("[bulk_review] 关闭刷新浏览器失败 account_id=%s: %s", account_id, exc)

# 待评价待办的判定：kind=ReviewedSeller 且 title=評価をしてください 且未软删
_REVIEW_TODO_TITLE = "評価をしてください"
_REVIEW_TODO_KIND = "ReviewedSeller"


def list_pending_review_todos(account_id: Optional[int] = None) -> List[Any]:
    """查未软删的「待评价」待办（可按账号过滤），按 mercari_updated 升序（旧的先评）。"""
    where = "[kind] = ? AND [title] = ? AND [is_delete] = 0"
    params: List[Any] = [_REVIEW_TODO_KIND, _REVIEW_TODO_TITLE]
    if account_id is not None:
        where += " AND [account_id] = ?"
        params.append(int(account_id))
    return TodoItemModel.find_all(
        where=where,
        params=tuple(params),
        order_by="[mercari_updated] ASC, [id] ASC",
    )


def pending_review_account_ids() -> List[int]:
    """有待评价待办的账号 id 列表（去重，保持稳定顺序）。"""
    seen: List[int] = []
    for todo in list_pending_review_todos():
        aid = int(getattr(todo, "account_id", 0) or 0)
        if aid and aid not in seen:
            seen.append(aid)
    return seen


async def bulk_submit_reviews_for_account(
    account_id: int,
    text: str = "",
    *,
    progress_job_id: Optional[str] = None,
    progress_prefix: str = "",
) -> Dict[str, Any]:
    """为单个账号下所有「評価をしてください」待办，复用同一 ``__todo`` 浏览器逐条提交好评。

    **必须在该账号的串行队列内调用**（不自取队列锁）。浏览器只开一次、结束统一关闭。
    返回 ``{account_id, ok, fail, total, failures: [...]}``。
    """
    report = make_sync_reporter(progress_job_id)
    body = (text or "").strip() or DEFAULT_REVIEW_TEXT

    todos = list_pending_review_todos(int(account_id))
    total = len(todos)
    if not total:
        return {"account_id": int(account_id), "ok": 0, "fail": 0, "total": 0, "failures": []}

    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(int(account_id))
    ok = 0
    fail = 0
    failures: List[str] = []
    completed_item_ids: List[str] = []

    first_item = (todos[0].item_id or "").strip()
    start_url = (
        f"https://jp.mercari.com/transaction/{first_item}"
        if first_item
        else "https://jp.mercari.com/mypage/todos"
    )

    try:
        # 评价为全自动操作，无需用户在浏览器内核对 → 始终无头静默运行
        async with mitm_automation_browser(
            int(account_id),
            start_url=start_url,
            headless=True,
            minimized=True,
            browser_key=auto_key,
        ) as (mgr, key):
            for idx, todo in enumerate(todos, start=1):
                item_id = (todo.item_id or "").strip()
                label = f"{progress_prefix}（{idx}/{total}）{item_id or ('#' + str(todo.id))}"
                report("bulk_review_item", f"正在提交评价 {label}…")
                if not item_id:
                    fail += 1
                    failures.append(f"#{todo.id}: 无 item_id")
                    continue
                url = f"https://jp.mercari.com/transaction/{item_id}"
                try:
                    await mgr.reload_active_tab(key, url)
                    page = await mgr.active_tab_page(key)
                    completed = await drive_review_on_page(page, body, aid=int(account_id))
                    if completed:
                        ok += 1
                        completed_item_ids.append(item_id)
                        _soft_delete_review_todo(todo)
                    else:
                        fail += 1
                        failures.append(f"#{todo.id} {item_id}: 未确认完成")
                except MercariLoginRequiredError:
                    # 登录态失效是账号级问题，交给外层统一处理剩余条目
                    raise
                except Exception as exc:  # noqa: BLE001 单条失败不阻断其余
                    fail += 1
                    failures.append(f"#{todo.id} {item_id}: {exc}")
                    log.warning("[bulk_review] 单条评价失败 todo_id=%s: %s", todo.id, exc)
    except MercariLoginRequiredError as exc:
        remaining = total - (ok + fail)
        if remaining > 0:
            fail += remaining
        failures.append(f"账号登录态失效：{exc}")
        log.warning(
            "[bulk_review] account_id=%s 登录态失效，剩余 %s 条跳过", account_id, max(remaining, 0)
        )
    finally:
        try:
            await mgr.close_session(auto_key, force=True)
        except Exception as exc:  # noqa: BLE001 关闭失败不阻断
            log.warning("[bulk_review] 关闭浏览器失败 account_id=%s: %s", account_id, exc)

    # 评价会话已关闭 → 复用 __sync 浏览器对本次评价完成的订单逐条回填财务字段
    await _refresh_orders_after_reviews(
        int(account_id), completed_item_ids, report, progress_prefix
    )

    return {
        "account_id": int(account_id),
        "ok": ok,
        "fail": fail,
        "total": total,
        "failures": failures,
    }
