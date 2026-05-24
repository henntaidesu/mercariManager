# -*- coding: utf-8 -*-
"""
留言（Comment 类型通知）详情同步入口：

- 打开账号主 profile 浏览器 → 导航到 ``jp.mercari.com/item/{item_id}``
- 经 MITM 截获 ``items/get`` 响应 → 提取商品基本信息 + ``comments`` 列表
- 不写库；调用方拿到结构化数据后直接返回前端展示
- **不使用队列**（与 bundle_purchase_decide 一致：直接复用主 profile 浏览器，
  完成后由队列空闲计时关闭即可）
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ...db_manage.models.meilu_account import MeiluAccountModel
from ...ssl_mitm_proxy.capture_config import clear_item_get_response_file
from ...web_drive.core.mitm_session import mitm_automation_browser
from .item_comment_capture import (
    build_item_page_url,
    capture_item_get_via_mitm_session,
    extract_item_with_comments,
)

log = logging.getLogger(__name__)


def _resolve_account_id(account_id: Optional[int]) -> int:
    if account_id is not None:
        acc = MeiluAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            raise ValueError(f"煤炉账号 id={account_id} 不存在")
        return int(account_id)
    rows = MeiluAccountModel.find_all(
        where="[status] = ? AND [is_open] = 1",
        params=("active",),
        order_by="[id] ASC",
        limit=1,
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active 且 is_open=1）")
    return int(rows[0].id)


async def sync_item_comments_from_mercari(
    *,
    item_id: str,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """打开 ``/item/{item_id}`` 抓取 items/get 响应,返回商品摘要 + 评论列表。

    返回结构：
        {
            "account_id": int,
            "item_id": str,
            "item": {id, name, price, status, thumbnail, num_comments, seller_id, ...},
            "comments": [{id, user_id, user_name, user_photo, message, created_ms}, ...],
        }
    """
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")

    aid = _resolve_account_id(account_id)
    log.info("[item_comment] sync start account_id=%s item_id=%s", aid, iid)

    clear_item_get_response_file(iid)
    since_ms = int(time.time() * 1000)
    start_url = build_item_page_url(iid)

    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, main_key):
        data = await capture_item_get_via_mitm_session(
            mgr, main_key, item_id=iid, since_ms=since_ms
        )

    if not isinstance(data, dict):
        raise RuntimeError(f"未截获 items/get 响应或响应体异常 item_id={iid}")

    parsed = extract_item_with_comments(data)
    log.info(
        "[item_comment] sync done account_id=%s item_id=%s comments=%d",
        aid, iid, len(parsed["comments"]),
    )
    return {
        "account_id": int(aid),
        "item_id": iid,
        **parsed,
    }
