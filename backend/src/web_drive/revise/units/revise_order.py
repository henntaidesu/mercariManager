# -*- coding: utf-8 -*-
"""
Mercari 在售商品修改：用同步/自动化专用无头 profile（mercari_{id}__sync）经 MITM 打开编辑页，填写「标题/价格/商品说明」
并点击「変更する」提交。提交成功后**不再从煤炉重新同步列表**，而是直接把改动写回本地
``on_sale_items`` 数据库（浏览器由队列空闲超时关闭）。

流程（cookie 由 Edge 持久化自动维护）：
  1. ``mitm_automation_browser(account_id, start_url=edit_url)`` 进入同步/自动化专用无头 profile ``mercari_{id}__sync``
  2. 填写 标题(input[name=name]) / 价格(input[name=price]) / 商品说明(textarea[name=description])
  3. 点击「変更する」(button[data-testid=edit-button]) 提交
  4. 直接 UPDATE 本地 on_sale_items 表对应记录
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...listing.units.post_to_macket import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
)
from ...delete.units.delete_order import (
    build_sell_edit_url,
    mercari_item_path_segment,
    _page_for_session,
)
from ....use_mercari.sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)

NAME_INPUT_SELECTOR = 'input[name="name"]'
PRICE_INPUT_SELECTOR = 'input[name="price"]'
# 可见的说明输入框（排除自动高度镜像用的只读 textarea）
DESC_TEXTAREA_SELECTOR = 'textarea[name="description"]:not([readonly])'
# 「変更する」提交按钮
SUBMIT_BTN_SELECTOR = 'button[data-testid="edit-button"]'


async def _fill_value(page: Any, selector: str, value: str, *, element_timeout_ms: int) -> None:
    """清空并填入输入框（React 受控组件，Playwright fill 会派发 input 事件）。"""
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.scroll_into_view_if_needed()
    await loc.fill("")
    await loc.fill(value)


def _update_local_on_sale_item(
    item_ids: List[str],
    *,
    name: Optional[str] = None,
    price: Optional[int] = None,
    description: Optional[str] = None,
) -> int:
    """把改动直接写回本地 on_sale_items 表（按 item_id 匹配，兼容带/不带 m 前缀）。"""
    from ....db_manage.database import DatabaseManager

    sets: List[str] = []
    params: List[Any] = []
    if name:
        sets.append("[name] = ?")
        params.append(name)
    if price is not None:
        sets.append("[price] = ?")
        params.append(int(price))
    if description is not None:
        sets.append("[listing_description] = ?")
        params.append(description)
    if not sets:
        return 0

    ids = [i for i in {str(x).strip() for x in item_ids} if i]
    if not ids:
        return 0

    db = DatabaseManager()
    placeholders = ",".join(["?"] * len(ids))
    sql = (
        f"UPDATE [on_sale_items] SET {', '.join(sets)} "
        f"WHERE TRIM(IFNULL([item_id], '')) IN ({placeholders})"
    )
    return int(db.execute_update(sql, tuple(params) + tuple(ids)) or 0)


async def revise_mercari_item(
    manager: Any,
    account_key: str,
    *,
    item_id: str,
    name: Optional[str] = None,
    price: Optional[int] = None,
    description: Optional[str] = None,
    proxy_server: Optional[str] = None,  # noqa: ARG001 — MITM 由 mitm_automation_browser 统一配置
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页修改商品并提交；提交后直接更新本地数据库
    （不重新同步在售列表）。上下文退出后浏览器由 ``account_serial_queue`` 在队列空闲超时后自动关闭。

    仅填写/更新传入的字段（name / price / description 任意组合）。
    """
    from ...core.manager import EdgeWebDriveManager
    from ...core.mitm_session import mitm_automation_browser
    from ...core.paths import mercari_automation_key, mercari_id_from_account_key

    report = make_sync_reporter(progress_job_id)

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")

    account_id = mercari_id_from_account_key(account_key)
    if account_id is None:
        raise ValueError(f"无效的 account_key: {account_key}")

    name_val = (name or "").strip()
    desc_val = description if description is not None else None
    price_val: Optional[int] = None
    if price is not None:
        try:
            price_val = int(price)
        except (TypeError, ValueError):
            price_val = None

    if not name_val and desc_val is None and price_val is None:
        raise ValueError("没有需要修改的字段")

    auto_key = mercari_automation_key(account_id)
    edit_url = build_sell_edit_url(item_id)

    log.info(
        "[revise_mercari_item] account=%s auto=%s item=%s url=%s",
        account_key,
        auto_key,
        seg,
        edit_url,
    )

    result: Dict[str, Any] = {
        "account_key": account_key,
        "browser_key": auto_key,
        "item_id": seg,
        "edit_url": edit_url,
        "filled": [],
        "revise_confirmed": False,
        "updated_rows": 0,
        "browser_closed": False,
    }

    report("open_edit_page", f"正在打开编辑页（{seg}）…")
    async with mitm_automation_browser(
        account_id,
        start_url=edit_url,
    ) as (mgr, browser_key):
        page = await _page_for_session(mgr, browser_key)

        try:
            await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
        except Exception:
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=page_load_timeout_ms
                )
            except Exception:
                pass

        report("fill_form", "正在填写商品信息…")
        if name_val:
            await _fill_value(
                page, NAME_INPUT_SELECTOR, name_val, element_timeout_ms=element_timeout_ms
            )
            result["filled"].append("name")
        if price_val is not None:
            await _fill_value(
                page, PRICE_INPUT_SELECTOR, str(price_val), element_timeout_ms=element_timeout_ms
            )
            result["filled"].append("price")
        if desc_val is not None:
            await _fill_value(
                page, DESC_TEXTAREA_SELECTOR, desc_val, element_timeout_ms=element_timeout_ms
            )
            result["filled"].append("description")

        await page.wait_for_timeout(500)

        report("submit", "正在提交修改「変更する」…")
        submit_btn = page.locator(SUBMIT_BTN_SELECTOR).first
        await submit_btn.wait_for(state="visible", timeout=element_timeout_ms)
        await submit_btn.scroll_into_view_if_needed()
        await submit_btn.click(timeout=element_timeout_ms)
        result["revise_confirmed"] = True

        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=page_load_timeout_ms
            )
        except Exception:
            pass
        await page.wait_for_timeout(2000)

    result["browser_closed"] = True

    # 提交成功后直接更新本地数据库（不重新同步）
    report("update_local", "正在更新本地数据…")
    raw_item_id = (item_id or "").strip()
    updated = _update_local_on_sale_item(
        [seg, raw_item_id],
        name=name_val or None,
        price=price_val,
        description=desc_val,
    )
    result["updated_rows"] = updated

    report("done", "修改完成")
    log.info(
        "[revise_mercari_item] 完成并已关闭浏览器 account=%s item=%s filled=%s updated_rows=%s",
        account_key,
        seg,
        result["filled"],
        updated,
    )
    return result
