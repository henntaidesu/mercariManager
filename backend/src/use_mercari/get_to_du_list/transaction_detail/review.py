# -*- coding: utf-8 -*-
"""review (ReviewedSeller): submit transaction review"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from ....db_manage.models.todos.todo_item import TodoItemModel
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ...sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


_REVIEW_TEXTAREA_PLACEHOLDER = "例) このたびはお取引ありがとうございました。"

_REVIEW_SUBMIT_BUTTON_TEXT = "購入者を評価して取引完了する"

_REVIEW_CONFIRM_BUTTON_TEXT = "取引を完了する"

_REVIEW_COMPLETED_TEXT = "取引が完了しました"

# 取引評価的两个单选（页面 input[name="fame"] 的 value ↔ 日文标签）
REVIEW_RATINGS = {"good": "良かった", "bad": "残念だった"}

# 切到「残念だった」时页面弹「「残念だった」に変更しますか？」→ 需再点「変更する」
_REVIEW_BAD_CONFIRM_BUTTON_TEXT = "変更する"

# 煤炉规则：残念だった 必须写理由，页面校验文案为
# 「残念だった評価には10文字以上の記入が必要です」。良かった 则允许留空
# （页面注脚：※コメントはなくてもかまいませんが…）。
REVIEW_BAD_MIN_LEN = 10

# 一键好评批量提交时的默认评价文本（前端未显式传入时回落）
DEFAULT_REVIEW_TEXT = "この度はお取引ありがとうございました。また機会がありましたらよろしくお願いします。"


def _soft_delete_review_todo(todo: Any) -> None:
    """评价完成后软删除本地 todo（页面已结案，对应煤炉端 todolist 下次同步也会剔除）。

    同时置本地完成标记 ``shipped_finalized=1``（通用「本地已完成、不得被同步复活」标记，
    不限发货类）：煤炉陈旧列表仍返回同 uuid 时，同步照抄 is_delete=0 会把该行复活回
    待评价，一键好评会再点一次并计入失败噪音。
    """
    try:
        todo.is_delete = 1
        todo.shipped_finalized = 1
        todo.synced_at = int(time.time() * 1000)
        todo.save()
        log.info("[review] 已软删除 todo_id=%s", getattr(todo, "id", None))
    except Exception as exc:
        log.warning("[review] 软删除 todo 失败: %s", exc)


async def _select_rating(page: Any, rating: str) -> None:
    """把取引評価的「良かった / 残念だった」单选切到 ``rating``（``good`` / ``bad``）。

    页面结构是 ``<label>…<input type="radio" name="fame" value="good|bad">``，input 被自绘
    样式盖住，所以点 label 让 React 自己冒泡；切「残念だった」还会弹一层
    「「残念だった」に変更しますか？」，要再点「変更する」才生效。

    最后**回读 input 的选中态**：点了没生效就抛错。评价一旦提交不可撤销，把 bad 当 good
    发出去是不可逆的错评。反过来 ``good`` 是页面默认值，读不到 radio 时按老行为继续
    （不因为页面改版把一键好评整条链路打死）。
    """
    label_text = REVIEW_RATINGS[rating]
    radio = page.locator(f'input[name="fame"][value="{rating}"]')
    try:
        await radio.first.wait_for(state="attached", timeout=4000)
    except Exception as exc:
        if rating == "good":
            log.warning("[review] 未找到评价单选（rating=good），按页面默认「良かった」继续: %s", exc)
            return
        raise RuntimeError(
            f"未找到「{label_text}」评价单选（当前 URL: {page.url}）"
        ) from exc

    if await radio.first.is_checked():
        log.info("[review] 评价单选已是「%s」，无需点击", label_text)
        return

    label = page.locator(f'label:has(input[name="fame"][value="{rating}"])')
    try:
        await label.first.click(timeout=4000)
    except Exception:
        await radio.first.click(force=True)

    if rating == "bad":
        confirm = page.get_by_role("button", name=_REVIEW_BAD_CONFIRM_BUTTON_TEXT)
        try:
            await confirm.first.wait_for(state="visible", timeout=3000)
            await confirm.first.click()
            log.info("[review] 已点击「%s」确认切到「残念だった」", _REVIEW_BAD_CONFIRM_BUTTON_TEXT)
        except Exception:
            log.info("[review] 未出现「残念だった」二次确认框，跳过")

    for _ in range(10):
        if await radio.first.is_checked():
            log.info("[review] 评价单选已切到「%s」", label_text)
            return
        await asyncio.sleep(0.3)
    raise RuntimeError(f"点击后「{label_text}」仍未选中（当前 URL: {page.url}）")


async def drive_review_on_page(
    page: Any,
    body: str,
    *,
    aid: int,
    rating: str = "good",
    report: Optional[Any] = None,
) -> bool:
    """在**已打开**的取引評価页上：选评价（良かった/残念だった）→ 填评价文本 →
    点「購入者を評価して取引完了する」→ 二次确认「取引を完了する」→ 等「取引が完了しました」。
    返回是否完成。

    仅负责页面驱动，不打开/关闭浏览器、不软删 todo——供单条 ``submit_transaction_review``
    与批量 ``bulk_submit_reviews_for_account`` 复用同一页面逻辑。``report`` 为可选进度回调
    ``(step, label_zh)``。``body`` 允许为空（页面上 良かった 的评论是任意项）。
    """
    def _r(step: str, label: str) -> None:
        if report is not None:
            report(step, label)

    # 先定评价，再填文本：切「残念だった」会弹确认框，压在文本框上面
    _r("select_rating", f"正在选择评价「{REVIEW_RATINGS[rating]}」…")
    await _select_rating(page, rating)

    # 找到评价 textarea（按 placeholder）
    _r("fill_review", "正在填入评价文本…")
    textarea = page.locator(f'textarea[placeholder="{_REVIEW_TEXTAREA_PLACEHOLDER}"]')
    try:
        await textarea.first.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到评价输入框（该交易可能已评价完成或页面未加载；当前 URL: {page.url}）"
        ) from exc
    await textarea.first.fill(body)
    log.info("[review] 已填入评价文本 text_len=%s", len(body))

    # 找到「購入者を評価して取引完了する」按钮
    _r("click_submit", "正在点击「購入者を評価して取引完了する」…")
    btn = page.get_by_role("button", name=_REVIEW_SUBMIT_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        btn = page.locator(f'button:has-text("{_REVIEW_SUBMIT_BUTTON_TEXT}")')
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_REVIEW_SUBMIT_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc
    await btn.first.click()
    log.info("[review] 已点击「%s」 account_id=%s", _REVIEW_SUBMIT_BUTTON_TEXT, aid)

    # 二次确认弹窗：「購入者を評価して取引を完了しますか？」→ 点「取引を完了する」
    _r("confirm_dialog", "正在点击二次确认「取引を完了する」…")
    await asyncio.sleep(0.3)
    confirm_btn = page.get_by_role("button", name=_REVIEW_CONFIRM_BUTTON_TEXT)
    try:
        await confirm_btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        confirm_btn = page.locator(f'button:has-text("{_REVIEW_CONFIRM_BUTTON_TEXT}")')
        try:
            await confirm_btn.first.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到二次确认按钮「{_REVIEW_CONFIRM_BUTTON_TEXT}」（当前 URL: {page.url}）"
            ) from exc
    await confirm_btn.first.click()
    log.info("[review] 已点击二次确认「%s」 account_id=%s", _REVIEW_CONFIRM_BUTTON_TEXT, aid)

    # 等页面刷新 + 检测「取引が完了しました」文案
    _r("wait_completed", "等待煤炉返回「取引が完了しました」…")
    try:
        completed_loc = page.get_by_text(_REVIEW_COMPLETED_TEXT, exact=False).first
        await completed_loc.wait_for(state="visible", timeout=15000)
        log.info("[review] 检测到「%s」 account_id=%s", _REVIEW_COMPLETED_TEXT, aid)
        return True
    except Exception:
        log.warning(
            "[review] 15s 内未检测到「%s」（可能已完成但页面文案变化；当前 URL: %s）",
            _REVIEW_COMPLETED_TEXT,
            page.url,
        )
        return False


async def submit_transaction_review(
    todo_id: int,
    text: str,
    *,
    rating: str = "good",
    progress_job_id: Optional[str] = None,
    force_headless: bool = False,
) -> Dict[str, Any]:
    """打开取引評価页（按商品 ID）→ 选评价 → 填评价文本 → 点「購入者を評価して取引完了する」
    → 二次确认。

    自带浏览器开启（不再依赖「处理」预先打开的会话）：提交评价为全自动操作，无需用户在
    浏览器内手动核对，故**始终无头静默**运行（不弹前台窗口）。``force_headless`` 保留为
    兼容参数，当前实现下提交评价一律无头。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备评价提交…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    rating = (rating or "good").strip().lower()
    if rating not in REVIEW_RATINGS:
        raise ValueError(f"未知的评价类型: {rating}")
    body = (text or "").strip()
    # 与页面同一套校验，先在本地拦下，省掉一趟白跑的浏览器
    if rating == "bad" and len(body) < REVIEW_BAD_MIN_LEN:
        raise ValueError(f"「残念だった」评价需填写 {REVIEW_BAD_MIN_LEN} 个字符以上的评论")

    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)

    report("open_browser", f"正在打开交易页（{item_id}）…")
    completed = False
    # 提交评价为全自动操作 → 始终无头静默（headless=True，minimized 自动失效）。
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=True,
        minimized=True,
        browser_key=auto_key,
    ) as (mgr, main_key):
        page = await mgr.active_tab_page(main_key)
        completed = await drive_review_on_page(page, body, aid=aid, rating=rating, report=report)

    order_refresh_error: Optional[str] = None
    if completed:
        report("finalize", "评价完成，正在收尾并刷新订单…")
        # 软删除本地 todo（页面已结案，对应煤炉端 todolist 也会下次同步剔除）
        _soft_delete_review_todo(todo)

        # 关浏览器
        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[review] 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[review] 关浏览器失败: %s", exc)

        # 刷新订单信息（按 item_id 等于 order_no 查 orders 表，回填 transaction_evidences 字段）
        if item_id:
            try:
                order_refresh_error = await apply_item_info_to_order(item_id, account_id=aid)
                if order_refresh_error:
                    log.warning("[review] 订单刷新返回错误: %s", order_refresh_error)
                else:
                    log.info("[review] 订单刷新完成 item_id=%s", item_id)
            except Exception as exc:
                order_refresh_error = f"exception:{exc}"
                log.warning("[review] 订单刷新异常: %s", exc)
        else:
            log.warning("[review] todo 无 item_id，跳过订单刷新")

    report("done", "评价已提交")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "rating": rating,
        "submitted": True,
        "confirmed": True,
        "completed": completed,
        "order_refresh_error": order_refresh_error,
        "text_len": len(body),
    }
