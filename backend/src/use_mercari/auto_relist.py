# -*- coding: utf-8 -*-
"""
自动出品（售出即补挂）。

当增量订单同步发现某商品的**新售出订单**时，若满足：
  · 该账号开启了「自动上架」同步项（mercari_accounts.auto_fetch_relist=1）
  · 该商品单品开关开启（inventory.auto_listing_enabled=1）
  · 仍有剩余可售库存（quantity - on_sale_quantity - pending_outbound_qty > 0）
则在售出该商品的同一煤炉账号下，用商品当前保存的出品设置 + 系统出品默认值，
复用既有出品自动化 `post_to_market` 把它重新上架。

出品说明末行写入管理番号暗号（``encode_mgmt_id``），下次在售同步即可把新挂牌
``item_id`` 重新绑回 ``inventory.id``，与手动「出品」保持一致。

去重：以 ``orders.auto_relisted`` 标记，一个售出订单最多触发一次补挂。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterable, List, Optional, Set

from ..db_manage.database import DatabaseManager
from ..db_manage.models.inventory import InventoryModel
from ..db_manage.models.mercari_account import MercariAccountModel
from ..db_manage.models.order import OrderModel
from ..db_manage.models.order_outbound_line import OrderOutboundLineModel
from ..db_manage.models.system_log import SystemLogModel
from .mgmt_id_cipher import encode_mgmt_id, is_cipher_mgmt_line

log = logging.getLogger(__name__)

# 持有 fire-and-forget task 的强引用，避免被 GC 提前回收
_RELIST_TASKS: Set["asyncio.Task"] = set()

# 出品说明总长上限（与手动出品 SingleListingFormDialog 一致）
_DESCRIPTION_MAX_LEN = 1000


def _account_relist_enabled(account_id: Optional[int]) -> bool:
    """该账号是否开启了「自动上架」同步项（账号级开关）。"""
    if account_id is None:
        return False
    try:
        acc = MercariAccountModel.find_by_id(id=int(account_id))
        return acc is not None and int(getattr(acc, "auto_fetch_relist", 0) or 0) == 1
    except Exception:
        return False


def schedule_auto_relist_for_orders(
    order_nos: Iterable[str],
    *,
    seller_id: Optional[str] = None,
    account_id: Optional[int] = None,
) -> None:
    """
    为若干新售出订单调度补挂（fire-and-forget）。

    每个订单一个独立 ``asyncio.create_task``：它内部会 ``await`` 账号串行队列，
    排在当前同步任务之后执行，从而避免在持有同账号队列槽的同步任务内再次入队导致的自我死锁。
    """
    nos = [str(x).strip() for x in (order_nos or []) if str(x or "").strip()]
    if not nos:
        return
    # 账号级「自动上架」开关：传入了 account_id 且未开启 → 直接跳过调度
    if account_id is not None and not _account_relist_enabled(account_id):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("[auto_relist] 无运行中的事件循环，跳过调度：%s", nos)
        return
    for ono in nos:
        task = loop.create_task(
            _relist_for_order(ono, seller_id=seller_id, account_id=account_id)
        )
        _RELIST_TASKS.add(task)
        task.add_done_callback(_RELIST_TASKS.discard)


def _resolve_account_id(seller_id: Optional[str], account_id: Optional[int]) -> Optional[int]:
    """优先用同步传入的 account_id；否则按 seller_id 反查 mercari_accounts。"""
    if account_id is not None:
        try:
            return int(account_id)
        except (TypeError, ValueError):
            pass
    sid = str(seller_id or "").strip()
    if not sid:
        return None
    rows = MercariAccountModel.find_all(
        where="TRIM(IFNULL([seller_id], '')) = TRIM(?)",
        params=(sid,),
        limit=1,
    )
    if not rows:
        return None
    try:
        return int(getattr(rows[0], "id"))
    except (TypeError, ValueError):
        return None


def _account_name(account_id: Optional[int]) -> Optional[str]:
    """取煤炉账号名（用于系统日志冗余展示）；取不到返回 None。"""
    if account_id is None:
        return None
    try:
        acc = MercariAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        name = str(getattr(acc, "account_name", "") or "").strip()
        return name or None
    except Exception:
        return None


def _inventory_ids_for_order(order_no: str) -> List[int]:
    lines = OrderOutboundLineModel.find_all(
        where="[order_no] = ? AND [inventory_id] IS NOT NULL",
        params=(order_no,),
    )
    out: List[int] = []
    seen: Set[int] = set()
    for ln in lines:
        try:
            iid = int(getattr(ln, "inventory_id"))
        except (TypeError, ValueError):
            continue
        if iid > 0 and iid not in seen:
            seen.add(iid)
            out.append(iid)
    return out


def _build_relist_description(body_raw: Optional[str], inventory_id: int) -> str:
    """正文去掉末行旧暗号后，追加本商品的管理番号暗号（沿用 1000 字截断逻辑）。"""
    body = str(body_raw or "").rstrip()
    # 去掉末尾仅由暗号组成的行（避免重复 / 旧暗号残留）
    lines = body.splitlines()
    while lines and (not lines[-1].strip() or is_cipher_mgmt_line(lines[-1])):
        lines.pop()
    body = "\n".join(lines).rstrip()
    foot = encode_mgmt_id(inventory_id)
    max_body = max(0, _DESCRIPTION_MAX_LEN - len(foot) - 2)
    if len(body) > max_body:
        body = body[:max_body]
    return f"{body}\n\n{foot}" if body else foot


def _inventory_image_urls(inv) -> List[str]:
    from ..use_web.inventory.units.inventory_helpers import (
        _inventory_paths_from_parsed_row,
    )

    return _inventory_paths_from_parsed_row(
        {
            "images_json": getattr(inv, "images_json", None),
            "image_front": getattr(inv, "image_front", None),
            "image": getattr(inv, "image", None),
            "image_back": getattr(inv, "image_back", None),
        }
    )


async def _relist_for_order(
    order_no: str,
    *,
    seller_id: Optional[str],
    account_id: Optional[int],
) -> None:
    """处理单个售出订单的补挂。全程吞异常，仅记日志，绝不影响同步主流程。"""
    try:
        orders = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not orders:
            return
        order = orders[0]
        if int(getattr(order, "auto_relisted", 0) or 0) == 1:
            return

        aid = _resolve_account_id(
            seller_id or getattr(order, "data_user", None), account_id
        )
        if aid is None:
            log.warning(
                "[auto_relist] 订单 %s 找不到对应煤炉账号（seller_id=%s），跳过补挂",
                order_no,
                seller_id or getattr(order, "data_user", None),
            )
            return
        # 账号级「自动上架」开关未开 → 不补挂（不标记，便于将来开启后由新订单触发）
        if not _account_relist_enabled(aid):
            return

        # 乐观占用：先标记已处理，避免重复触发造成重复上架（上架涉及真实挂牌）。
        DatabaseManager().execute_update(
            "UPDATE [orders] SET [auto_relisted] = 1 WHERE [order_no] = ?",
            (order_no,),
        )

        inventory_ids = _inventory_ids_for_order(order_no)
        if not inventory_ids:
            return

        for inv_id in inventory_ids:
            try:
                await _relist_single_inventory(inv_id, aid)
            except Exception as exc:  # 单品失败不影响同订单其它商品
                log.exception("[auto_relist] 商品 %s 补挂异常：%s", inv_id, exc)
    except Exception as exc:
        log.exception("[auto_relist] 订单 %s 补挂异常：%s", order_no, exc)


async def _relist_single_inventory(inventory_id: int, account_id: int) -> None:
    inv = InventoryModel.find_by_id(id=inventory_id)
    if inv is None:
        return
    if int(getattr(inv, "auto_listing_enabled", 0) or 0) != 1:
        return

    quantity = int(getattr(inv, "quantity", 0) or 0)
    on_sale = int(getattr(inv, "on_sale_quantity", 0) or 0)
    pending = int(getattr(inv, "pending_outbound_qty", 0) or 0)
    available = quantity - on_sale - pending
    if available <= 0:
        log.info(
            "[auto_relist] 商品 %s 无剩余可售库存（quantity=%s on_sale=%s pending=%s），跳过",
            inventory_id, quantity, on_sale, pending,
        )
        return

    product_type_id = getattr(inv, "product_type_id", None)
    if product_type_id is None:
        log.warning("[auto_relist] 商品 %s 缺少 product_type_id（商品类型），跳过", inventory_id)
        return

    image_urls = _inventory_image_urls(inv)
    if not image_urls:
        log.warning("[auto_relist] 商品 %s 无可用图片，跳过", inventory_id)
        return

    name = (
        str(getattr(inv, "listing_title", "") or "").strip()
        or str(getattr(inv, "name", "") or "").strip()
    )
    if not name:
        log.warning("[auto_relist] 商品 %s 缺少出品标题/名称，跳过", inventory_id)
        return

    body_raw = getattr(inv, "listing_body", None) or getattr(inv, "description", None)
    description = _build_relist_description(body_raw, inventory_id)
    price = int(getattr(inv, "price", 0) or 0)

    # 出品设置：优先商品自身保存值，缺省回落系统出品默认值
    from ..use_web.system.units.app_config_handler import _read_listing_defaults

    ld = _read_listing_defaults()

    def _pick(item_val, cfg_val, fallback):
        s = str(item_val if item_val is not None else "").strip()
        if s:
            return s
        s2 = str(cfg_val if cfg_val is not None else "").strip()
        return s2 or fallback

    status = _pick(getattr(inv, "listing_status", None), ld.get("condition"), "new_unused")
    sale_type = _pick(getattr(inv, "sale_type", None), ld.get("sale_type"), "instant_buy")
    shipping_payer = _pick(getattr(inv, "shipping_payer", None), ld.get("shipping_payer"), "seller")
    shipping_method = _pick(getattr(inv, "shipping_method", None), ld.get("shipping_method"), "undecided")
    shipping_days = _pick(getattr(inv, "shipping_days", None), ld.get("shipping_days"), "2_3_days")
    shipping_from_area_id = _pick(
        getattr(inv, "shipping_from_area_id", None), ld.get("shipping_from_area_id"), ""
    )
    auction_duration = str(getattr(inv, "auction_duration", None) or "normal").strip() or "normal"
    if not shipping_from_area_id:
        log.warning(
            "[auto_relist] 商品 %s：系统出品默认未配置发货地，出品可能失败（仍尝试）",
            inventory_id,
        )

    # 复用既有出品自动化（按账号串行队列、类目 position、MITM 代理全在其中）
    from ..web_drive.core.paths import mercari_account_key
    from ..use_web.web_drive.units.web_drive_handler import (
        PostToMarketBody,
        post_to_market,
    )

    body = PostToMarketBody(
        account_key=mercari_account_key(account_id),
        name=name,
        description=description,
        image_urls=image_urls,
        category_mapping_id=str(product_type_id),
        status=status,
        shipping_payer=shipping_payer,
        shipping_method=shipping_method,
        sale_type=sale_type,
        auction_duration=auction_duration,
        price=price,
        shipping_days=shipping_days,
        shipping_from_area_id=shipping_from_area_id,
        use_mitm_proxy=True,
    )

    account_name = _account_name(account_id)

    log.info(
        "[auto_relist] 商品 %s 触发补挂：account_id=%s price=%s name=%s",
        inventory_id, account_id, price, name,
    )
    try:
        res = await post_to_market(body)
    except Exception as exc:
        log.exception("[auto_relist] 商品 %s 出品自动化失败：%s", inventory_id, exc)
        SystemLogModel.add(
            category="auto_relist",
            level="error",
            account_id=account_id,
            account_name=account_name,
            message=f"重新上架失败：#{inventory_id} {name}（¥{price}）：{exc}",
            detail={"inventory_id": inventory_id, "name": name, "price": price,
                    "account_id": account_id, "error": str(exc)},
        )
        return
    submit_msg = None
    try:
        data = (res or {}).get("data") if isinstance(res, dict) else None
        submit_msg = (data or {}).get("submit_message") if isinstance(data, dict) else None
        log.info(
            "[auto_relist] 商品 %s 出品自动化完成：%s",
            inventory_id, submit_msg or "(无消息)",
        )
    except Exception:
        pass
    SystemLogModel.add(
        category="auto_relist",
        level="info",
        account_id=account_id,
        account_name=account_name,
        message=f"重新上架：#{inventory_id} {name}（¥{price}）",
        detail={"inventory_id": inventory_id, "name": name, "price": price,
                "account_id": account_id, "submit_message": submit_msg},
    )
