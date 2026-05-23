# -*- coding: utf-8 -*-
"""煤炉账号管理 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/meilu_accounts
- 完整 URL 示例: GET /mercariV2/src/use_web/meilu_accounts/
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ...db_manage.models.meilu_account import MeiluAccountModel
from ...ssl_mitm_proxy.capture_config import (
    clear_session_marker,
    read_capture_file,
    write_session_marker_ms,
)
from ...ssl_mitm_proxy.runner import (
    default_mitm_proxy_url,
    mitm_status,
    start_mitm_proxy,
)
from ...web_drive import get_web_drive_manager

router = APIRouter()
log = logging.getLogger(__name__)

ALLOWED_STATUS = {"active", "disabled"}
# 前端主选项 15/30/1H/3H/6H；保留旧值以便已存数据校验通过
ALLOWED_FETCH_INTERVALS = frozenset({"15", "30", "60", "3h", "6h", "10", "12h", "24h"})
MERCARI_IN_PROGRESS_URL = "https://jp.mercari.com/mypage/listings/in_progress"
MERCARI_LISTINGS_URL = "https://jp.mercari.com/mypage/listings"
IN_PROGRESS_FIRST_LINK_XPATH = '//*[@id="my-page-main-content"]/div/div/div/div/ul/li[1]/a/div[1]/div'
LISTINGS_FIRST_ITEM_XPATH = '//*[@id="my-page-main-content"]/div/div/div/div/ul/li[1]/a/div[1]/div/span[1]'
IN_PROGRESS_CLICK_XPATH_CANDIDATES = (
    IN_PROGRESS_FIRST_LINK_XPATH,
    '//*[@id="my-page-main-content"]/div/div/div/div/ul/li[1]/a/div[1]/div/span[1]',
    '//*[@id="my-page-main-content"]//ul/li[1]//a',
)

# 与 jp.mercari.com Web 抓包一致；可选：在售列表 / 单件详情专用 DPoP
_HEADER_FIELD_LABELS = [
    ("x_platform", "X-Platform"),
    ("authorization", "Authorization"),
    ("sec_ch_ua_platform", "Sec-CH-UA-Platform"),
    ("accept_language", "Accept-Language"),
    ("sec_ch_ua", "Sec-CH-UA"),
    ("sec_ch_ua_mobile", "Sec-CH-UA-Mobile"),
    ("dpop_list", "DPoP_List"),
    ("dpop_info", "DPoP_Info"),
    ("dpop_on_sale_list", "DPoP_OnSale-List"),
    ("dpop_item_get_info", "DPoP_ItemGet-Info"),
    ("user_agent", "User-Agent"),
    ("accept", "Accept"),
    ("origin", "Origin"),
    ("sec_fetch_site", "Sec-Fetch-Site"),
    ("sec_fetch_mode", "Sec-Fetch-Mode"),
    ("sec_fetch_dest", "Sec-Fetch-Dest"),
    ("referer", "Referer"),
    ("accept_encoding", "Accept-Encoding"),
    ("priority", "Priority"),
]


class MeiluAccountCreate(PydanticModel):
    account_name: str
    """省略或全空时存 {}，后续可通过 MITM 等写入完整请求头。"""
    value: Optional[Dict[str, Any]] = None
    login_id: Optional[str] = None
    seller_id: Optional[str] = None
    status: str = "disabled"
    remark: Optional[str] = None
    is_open: int = 0
    fetch_interval: Optional[str] = None
    auto_fetch_order_status: int = 0
    auto_fetch_order_list: int = 0
    auto_fetch_on_sale: int = 0


class MeiluAccountUpdate(PydanticModel):
    account_name: Optional[str] = None
    login_id: Optional[str] = None
    seller_id: Optional[str] = None
    value: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    remark: Optional[str] = None
    is_open: Optional[int] = None
    fetch_interval: Optional[str] = None
    auto_fetch_order_status: Optional[int] = None
    auto_fetch_order_list: Optional[int] = None
    auto_fetch_on_sale: Optional[int] = None


class FetchAuthViaMitmBody(PydanticModel):
    """通过 MITM 按顺序抓取 4 个 DPoP 字段并写回账号。"""

    wait_seconds: int = Field(15, ge=5, le=300)
    open_browser: bool = True
    in_progress_xpath: str = IN_PROGRESS_FIRST_LINK_XPATH
    first_item_xpath: str = LISTINGS_FIRST_ITEM_XPATH


class FetchSellerIdViaMitmBody(PydanticModel):
    """打开出品一覧页，经 MITM 截获 items/get_items（on_sale,stop）并从 URL 解析 seller_id。"""

    account_key: str = Field(
        default="meilu_prepare",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    wait_seconds: int = Field(90, ge=10, le=300)
    headless: bool = False
    close_browser_after: bool = False


def _validate_status(status: str):
    if status not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="账号状态错误")


def _norm_required_text(value: str, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    return text


def _norm_seller_id(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    if not text.isdigit():
        raise HTTPException(status_code=400, detail="卖家ID必须为数字")
    return text


def _normalize_is_open(v: Any) -> int:
    if v is True:
        return 1
    if v is False or v is None:
        return 0
    try:
        return 1 if int(v) else 0
    except (TypeError, ValueError):
        return 0


def _norm_auto_fetch(
    is_open: int,
    fetch_interval: Optional[str],
    order_status: int,
    order_list: int,
    on_sale: int,
) -> tuple:
    """
    规范化自动同步：总开关关闭时清空间隔与子任务；
    开启时须合法间隔且至少一项子任务为 1。
    """
    io = 1 if is_open else 0
    if io == 0:
        return 0, None, 0, 0, 0
    iv = (fetch_interval or "").strip()
    if iv not in ALLOWED_FETCH_INTERVALS:
        raise HTTPException(status_code=400, detail="开启自动数据获取时，请选择有效的时间间隔")
    st = 1 if order_status else 0
    li = 1 if order_list else 0
    os_ = 1 if on_sale else 0
    if not (st or li or os_):
        raise HTTPException(status_code=400, detail="开启自动数据获取时，请至少选择一项同步任务")
    return 1, iv, st, li, os_


def _norm_headers_dict(d: Optional[dict]) -> dict:
    if not d or not isinstance(d, dict):
        raise HTTPException(status_code=400, detail="请求头 value 必须为 JSON 对象")
    # 旧版仅存 dpop：视为 dpop_list；仅有一条 DPoP 时 dpop_info 可暂与 list 相同
    d = dict(d)
    if not (str(d.get("dpop_list") or "").strip()) and (str(d.get("dpop") or "").strip()):
        d["dpop_list"] = str(d["dpop"]).strip()
    out = {}
    for key, label in _HEADER_FIELD_LABELS:
        raw = d.get(key)
        text = ("" if raw is None else str(raw)).strip()
        # 订单详情 / 在售列表 / 单件详情 等专用 DPoP：可选；不填则调用对应接口时再报错提示补全
        if key in ("dpop_info", "dpop_on_sale_list", "dpop_item_get_info"):
            out[key] = text
            continue
        if not text:
            raise HTTPException(status_code=400, detail=f"{label}不能为空")
        out[key] = text
    return out


def _mitm_patch_console_lines(patch: Dict[str, Any]) -> List[str]:
    """供终端打印：敏感字段只显示长度与前缀。"""
    lines: List[str] = []
    for k in sorted((patch or {}).keys()):
        v = str(patch.get(k) or "")
        if k in ("authorization", "dpop_list", "dpop_info", "dpop_on_sale_list", "dpop_item_get_info"):
            lines.append(f"  • {k}: 长度 {len(v)}，前缀 {v[:24]}…")
        else:
            disp = v.replace("\n", " ")
            if len(disp) > 100:
                disp = disp[:97] + "…"
            lines.append(f"  • {k}: {disp}")
    return lines


def _apply_mitm_patch_to_account(item: MeiluAccountModel, patch: Dict[str, Any]) -> None:
    """将 MITM 写入的 value_patch 合并进现有 value，再经 _norm_headers_dict 校验。"""
    cur = MeiluAccountModel._parse_value_json(item.value)
    for k, v in (patch or {}).items():
        if v is not None and str(v).strip():
            cur[str(k)] = str(v).strip()
    if cur.get("dpop_list") and not (cur.get("dpop_info") or "").strip():
        cur["dpop_info"] = cur["dpop_list"]
    normalized = _norm_headers_dict(cur)
    item.value = json.dumps(normalized, ensure_ascii=False)


def _item_api_dict(item: MeiluAccountModel) -> dict:
    d = item.to_dict()
    d.pop('login_password', None)
    raw = d.pop('value', None)
    d['value'] = MeiluAccountModel._parse_value_json(raw if isinstance(raw, str) else None)
    d['is_open'] = 1 if d.get('is_open') else 0
    d['auto_fetch_order_status'] = 1 if d.get('auto_fetch_order_status') else 0
    d['auto_fetch_order_list'] = 1 if d.get('auto_fetch_order_list') else 0
    d['auto_fetch_on_sale'] = 1 if d.get('auto_fetch_on_sale') else 0
    return d


async def _wait_capture(
    *,
    since_ms: int,
    capture_type: str,
    wait_seconds: int,
    seller_id: Optional[str] = None,
    dpop_field: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        # 直接读该 capture_type 专属文件，不受其他类型请求覆盖干扰
        data = read_capture_file(capture_type)
        if data and int(data.get("ts") or 0) >= since_ms:
            if seller_id:
                sid = str(data.get("seller_id") or "").strip()
                if sid and sid != seller_id:
                    await asyncio.sleep(0.9)
                    continue
            if dpop_field:
                df = str(data.get("dpop_field") or "").strip()
                if df != dpop_field:
                    await asyncio.sleep(0.9)
                    continue
            return data
        await asyncio.sleep(0.9)
    return None


async def _wait_capture_with_progress(
    *,
    since_ms: int,
    capture_type: str,
    wait_seconds: int,
    seller_id: Optional[str] = None,
    dpop_field: Optional[str] = None,
    acquired_fields: Optional[List[str]] = None,
    step_name: str = "",
    url_contains: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """等待捕获并每 3 秒打印一次进度（CLI 可见）。"""
    acquired_fields = acquired_fields or []
    deadline = time.monotonic() + wait_seconds
    next_log_at = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_log_at:
            got = "、".join(acquired_fields) if acquired_fields else "无"
            left = max(0, int(deadline - now))
            msg = (
                f"[MITM][进度] 当前步骤: {step_name or capture_type} | "
                f"已获取字段: {got} | 剩余约 {left}s"
            )
            log.info(msg)
            print(msg, flush=True)
            next_log_at = now + 3.0
        # 直接读该 capture_type 专属文件，不受其他类型请求覆盖干扰
        data = read_capture_file(capture_type)
        if data and int(data.get("ts") or 0) >= since_ms:
            if seller_id:
                sid = str(data.get("seller_id") or "").strip()
                if sid and sid != seller_id:
                    await asyncio.sleep(0.9)
                    continue
            if dpop_field:
                df = str(data.get("dpop_field") or "").strip()
                if df != dpop_field:
                    await asyncio.sleep(0.9)
                    continue
            if url_contains:
                u = str(data.get("url") or "")
                if url_contains not in u:
                    await asyncio.sleep(0.9)
                    continue
            return data
        await asyncio.sleep(0.9)
    return None


async def _click_first_match_xpath(mgr: Any, account_key: str, xpaths: List[str], timeout_ms: int = 25000) -> str:
    """按顺序尝试点击多个 XPath，返回成功的 XPath。"""
    last_exc: Optional[Exception] = None
    for xp in xpaths:
        try:
            await mgr.click_xpath(account_key, xp, timeout_ms=timeout_ms)
            return xp
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"所有候选 XPath 点击失败: {last_exc}")


@router.get("")
def list_meilu_accounts(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if status:
        _validate_status(status)
    return MeiluAccountModel.find_detail_list(
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )


def _value_json_for_create(data: MeiluAccountCreate) -> str:
    raw = data.value
    if not raw or not isinstance(raw, dict):
        return json.dumps({}, ensure_ascii=False)
    if not any(str(v or "").strip() for v in raw.values()):
        return json.dumps({}, ensure_ascii=False)
    headers = _norm_headers_dict(raw)
    return json.dumps(headers, ensure_ascii=False)


@router.post("")
def create_meilu_account(data: MeiluAccountCreate):
    _validate_status(data.status)
    value_json = _value_json_for_create(data)
    name = _norm_required_text(data.account_name, "账号名称")
    lid = (data.login_id or "").strip() or name
    io, fi, st, li, os_ = _norm_auto_fetch(
        _normalize_is_open(data.is_open),
        data.fetch_interval,
        _normalize_is_open(data.auto_fetch_order_status),
        _normalize_is_open(data.auto_fetch_order_list),
        _normalize_is_open(data.auto_fetch_on_sale),
    )
    item = MeiluAccountModel(
        account_name=name,
        login_id=lid,
        seller_id=_norm_seller_id(data.seller_id),
        login_password=None,
        value=value_json,
        status=data.status,
        remark=data.remark,
        is_open=io,
        fetch_interval=fi,
        auto_fetch_order_status=st,
        auto_fetch_order_list=li,
        auto_fetch_on_sale=os_,
    )
    if not item.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _item_api_dict(item)


@router.put("/{aid}")
def update_meilu_account(aid: int, data: MeiluAccountUpdate):
    item = MeiluAccountModel.find_by_id(id=aid)
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")

    if data.account_name is not None:
        item.account_name = _norm_required_text(data.account_name, "账号名称")
    if data.login_id is not None:
        item.login_id = (data.login_id or "").strip() or item.account_name
    if data.seller_id is not None:
        item.seller_id = _norm_seller_id(data.seller_id)
    if data.status is not None:
        _validate_status(data.status)
        item.status = data.status
    if data.remark is not None:
        item.remark = data.remark
    if data.value is not None:
        headers = _norm_headers_dict(data.value)
        item.value = json.dumps(headers, ensure_ascii=False)
    if data.is_open is not None or data.fetch_interval is not None or data.auto_fetch_order_status is not None or data.auto_fetch_order_list is not None or data.auto_fetch_on_sale is not None:
        prev_open = _normalize_is_open(item.is_open)
        io = _normalize_is_open(data.is_open) if data.is_open is not None else prev_open
        fi = data.fetch_interval if data.fetch_interval is not None else item.fetch_interval
        st = _normalize_is_open(getattr(item, "auto_fetch_order_status", 0))
        if data.auto_fetch_order_status is not None:
            st = _normalize_is_open(data.auto_fetch_order_status)
        li = _normalize_is_open(getattr(item, "auto_fetch_order_list", 0))
        if data.auto_fetch_order_list is not None:
            li = _normalize_is_open(data.auto_fetch_order_list)
        os_ = _normalize_is_open(getattr(item, "auto_fetch_on_sale", 0))
        if data.auto_fetch_on_sale is not None:
            os_ = _normalize_is_open(data.auto_fetch_on_sale)
        io, fi, st, li, os_ = _norm_auto_fetch(io, fi, st, li, os_)
        item.is_open = io
        item.fetch_interval = fi
        item.auto_fetch_order_status = st
        item.auto_fetch_order_list = li
        item.auto_fetch_on_sale = os_
        if io == 0:
            item.auto_fetch_last_at = None
        elif prev_open == 0 and io == 1:
            item.auto_fetch_last_at = None

    if not item.save():
        raise HTTPException(status_code=500, detail="更新失败")
    return _item_api_dict(item)


@router.post("/fetch-seller-id-via-mitm")
async def fetch_seller_id_via_mitm(
    body: FetchSellerIdViaMitmBody = Body(default_factory=FetchSellerIdViaMitmBody),
):
    """
    启动 MITM，用指定 WebDrive 会话（如 meilu_prepare / meilu_{id}）经代理打开
    jp.mercari.com/mypage/listings，截获
    GET api.mercari.jp/items/get_items?status=on_sale,stop&... 并从查询参数读取 seller_id。
    """
    r = start_mitm_proxy()
    if r.get("error"):
        raise HTTPException(status_code=500, detail=r["error"])

    account_key = (body.account_key or "meilu_prepare").strip()
    t0 = int(time.time() * 1000)
    mgr = get_web_drive_manager()
    opened_here = False
    try:
        await mgr.open_session(
            account_key,
            headless=body.headless,
            start_url=MERCARI_LISTINGS_URL,
            proxy_server=default_mitm_proxy_url(),
            interactive=not body.headless,
        )
        opened_here = True

        cap = await _wait_capture_with_progress(
            since_ms=t0,
            capture_type="items_get_items",
            wait_seconds=body.wait_seconds,
            dpop_field="dpop_on_sale_list",
            step_name="在售列表 seller_id",
        )
        if not cap:
            raise HTTPException(
                status_code=408,
                detail=(
                    "超时：未截获 GET /items/get_items（status 含 on_sale/stop）。"
                    "请确认 MITM 已启动、Edge 已登录煤炉且出品一覧可正常加载。"
                ),
            )

        sid = _norm_seller_id(str(cap.get("seller_id") or "").strip())
        if not sid:
            raise HTTPException(status_code=500, detail="截获请求中未解析到有效 seller_id")

        log.info(
            "[MITM] 已解析 seller_id=%s account_key=%s url=%s",
            sid,
            account_key,
            cap.get("url") or "",
        )
        return {
            "success": True,
            "data": {
                "seller_id": sid,
                "url": cap.get("url"),
                "ts": cap.get("ts"),
                "account_key": account_key,
            },
            "mitm": mitm_status(),
        }
    finally:
        if body.close_browser_after and opened_here:
            try:
                await mgr.close_session(account_key, force=True)
            except Exception as exc:
                log.warning("[MITM] 获取 seller_id 后关闭浏览器失败 key=%s: %s", account_key, exc)


@router.post("/{aid}/fetch-auth-via-mitm")
async def fetch_auth_via_mitm(
    aid: int,
    body: Optional[FetchAuthViaMitmBody] = Body(default=None),
):
    """
    启动 MITM（若未运行），按固定顺序抓取并写回：
    1) DPoP_List: GET /items/get_items?status=trading
    2) DPoP_Info: GET /transaction_evidences/get
    3) DPoP_OnSale-List: GET /items/get_items?status=on_sale|stop
    4) DPoP_ItemGet-Info: GET /items/get
    """
    cfg = body or FetchAuthViaMitmBody()
    r = start_mitm_proxy()
    if r.get("error"):
        raise HTTPException(status_code=500, detail=r["error"])

    item = MeiluAccountModel.find_by_id(id=aid)
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")
    sid_cfg = _norm_seller_id(item.seller_id)
    if not sid_cfg:
        raise HTTPException(status_code=400, detail="请先填写卖家 ID（须与请求中 seller_id 一致）")

    t0 = int(time.time() * 1000)
    write_session_marker_ms(aid, t0)
    try:
        mgr = None
        if cfg.open_browser:
            mgr = get_web_drive_manager()
            from ...web_drive.paths import meilu_automation_key, seed_automation_profile_from_account

            auto_key = meilu_automation_key(aid)
            await mgr.close_session(auto_key, force=True)
            seed_automation_profile_from_account(aid)
            await mgr.open_session(
                auto_key,
                headless=False,
                start_url=MERCARI_IN_PROGRESS_URL,
                proxy_server=default_mitm_proxy_url(),
                interactive=False,
            )

        patch: Dict[str, Any] = {}
        capture_meta: Dict[str, Any] = {"seller_id": sid_cfg}
        acquired_fields: List[str] = []

        # Step 1: DPoP_List
        cap_list = await _wait_capture_with_progress(
            since_ms=t0,
            capture_type="items_get_items",
            wait_seconds=cfg.wait_seconds,
            seller_id=sid_cfg,
            dpop_field="dpop_list",
            acquired_fields=acquired_fields,
            step_name="Step 1/4 DPoP_List",
        )
        if not cap_list:
            raise HTTPException(status_code=408, detail="步骤1失败：未截获 DPoP_List（GET /items/get_items?status=trading）")
        print(f"[MITM] 截获 URL(1/4 dpop_list): {cap_list.get('url') or ''}", flush=True)
        patch.update(cap_list.get("value_patch") or {})
        if not str(patch.get("dpop_list") or "").strip():
            raise HTTPException(status_code=500, detail="步骤1失败：截获到请求但缺少 dpop_list")
        acquired_fields.append("dpop_list")
        capture_meta["dpop_list_url"] = cap_list.get("url")
        capture_meta["dpop_list_ts"] = cap_list.get("ts")
        log.info("[MITM] Step 1 完成，等待 3s 后进入 Step 2")
        print("[MITM] Step 1 完成，等待 3s 后进入 Step 2", flush=True)
        await asyncio.sleep(3)

        # Step 2: DPoP_Info
        if cfg.open_browser and mgr is not None:
            try:
                # 先确保处于「取引中」页，再点击首条交易触发 transaction_evidences/get
                await mgr.open_new_tab(auto_key, MERCARI_IN_PROGRESS_URL)
                clicked = await _click_first_match_xpath(
                    mgr,
                    auto_key,
                    [cfg.in_progress_xpath, *list(IN_PROGRESS_CLICK_XPATH_CANDIDATES)],
                    timeout_ms=25000,
                )
                log.info("[MITM] Step 2 点击成功 XPath: %s", clicked)
                print(f"[MITM] Step 2 点击成功 XPath: {clicked}", flush=True)
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"步骤2前置失败：自动点击「取引中」首条失败（可能无取引中数据或页面结构变化）: {exc}",
                ) from exc
        cap_info = await _wait_capture_with_progress(
            since_ms=int(cap_list.get("ts") or t0),
            capture_type="transaction_evidences_get",
            wait_seconds=cfg.wait_seconds,
            dpop_field="dpop_info",
            acquired_fields=acquired_fields,
            step_name="Step 2/4 DPoP_Info",
            url_contains="/transaction_evidences/get?",
        )
        if not cap_info:
            raise HTTPException(status_code=408, detail="步骤2失败：未截获 DPoP_Info（GET /transaction_evidences/get）")
        print(f"[MITM] 截获 URL(2/4 dpop_info): {cap_info.get('url') or ''}", flush=True)
        patch.update(cap_info.get("value_patch") or {})
        if not str(patch.get("dpop_info") or "").strip():
            raise HTTPException(status_code=500, detail="步骤2失败：截获到请求但缺少 dpop_info")
        acquired_fields.append("dpop_info")
        capture_meta["dpop_info_url"] = cap_info.get("url")
        capture_meta["dpop_info_ts"] = cap_info.get("ts")
        log.info("[MITM] Step 2 完成，等待 3s 后进入 Step 3")
        print("[MITM] Step 2 完成，等待 3s 后进入 Step 3", flush=True)
        await asyncio.sleep(3)

        # Step 3: DPoP_OnSale-List
        if cfg.open_browser and mgr is not None:
            await mgr.open_new_tab(auto_key, MERCARI_LISTINGS_URL)
        cap_on_sale = await _wait_capture_with_progress(
            since_ms=int(cap_info.get("ts") or t0),
            capture_type="items_get_items",
            wait_seconds=cfg.wait_seconds,
            seller_id=sid_cfg,
            dpop_field="dpop_on_sale_list",
            acquired_fields=acquired_fields,
            step_name="Step 3/4 DPoP_OnSale-List",
        )
        if not cap_on_sale:
            raise HTTPException(status_code=408, detail="步骤3失败：未截获 DPoP_OnSale-List（GET /items/get_items?status=on_sale|stop）")
        print(f"[MITM] 截获 URL(3/4 dpop_on_sale_list): {cap_on_sale.get('url') or ''}", flush=True)
        patch.update(cap_on_sale.get("value_patch") or {})
        if not str(patch.get("dpop_on_sale_list") or "").strip():
            raise HTTPException(status_code=500, detail="步骤3失败：截获到请求但缺少 dpop_on_sale_list")
        acquired_fields.append("dpop_on_sale_list")
        capture_meta["dpop_on_sale_list_url"] = cap_on_sale.get("url")
        capture_meta["dpop_on_sale_list_ts"] = cap_on_sale.get("ts")
        log.info("[MITM] Step 3 完成，等待 3s 后进入 Step 4")
        print("[MITM] Step 3 完成，等待 3s 后进入 Step 4", flush=True)
        await asyncio.sleep(3)

        # Step 4: DPoP_ItemGet-Info
        if cfg.open_browser and mgr is not None:
            try:
                await mgr.click_xpath(auto_key, cfg.first_item_xpath, timeout_ms=25000)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"步骤4前置失败：自动点击「出品中」首条失败: {exc}") from exc
        cap_item_get = await _wait_capture_with_progress(
            since_ms=int(cap_on_sale.get("ts") or t0),
            capture_type="items_get",
            wait_seconds=cfg.wait_seconds,
            dpop_field="dpop_item_get_info",
            acquired_fields=acquired_fields,
            step_name="Step 4/4 DPoP_ItemGet-Info",
        )
        if not cap_item_get:
            raise HTTPException(status_code=408, detail="步骤4失败：未截获 DPoP_ItemGet-Info（GET /items/get）")
        print(f"[MITM] 截获 URL(4/4 dpop_item_get_info): {cap_item_get.get('url') or ''}", flush=True)
        patch.update(cap_item_get.get("value_patch") or {})
        if not str(patch.get("dpop_item_get_info") or "").strip():
            raise HTTPException(status_code=500, detail="步骤4失败：截获到请求但缺少 dpop_item_get_info")
        acquired_fields.append("dpop_item_get_info")
        capture_meta["dpop_item_get_info_url"] = cap_item_get.get("url")
        capture_meta["dpop_item_get_info_ts"] = cap_item_get.get("ts")

        sid_cap = _norm_seller_id(str(cap_on_sale.get("seller_id") or sid_cfg).strip())
        if not sid_cap:
            raise HTTPException(status_code=500, detail="捕获中缺少有效 seller_id")
        item.seller_id = sid_cap

        _apply_mitm_patch_to_account(item, patch)
        if not item.save():
            raise HTTPException(status_code=500, detail="保存失败")

        keys_sorted = sorted(patch.keys())
        log.info(
            "[MITM] 捕获已写入账号 id=%s seller_id=%s ts=%s",
            aid,
            sid_cap,
            cap_item_get.get("ts"),
        )
        log.info("[MITM] 截获 URL(1/4 dpop_list): %s", cap_list.get("url") or "")
        log.info("[MITM] 截获 URL(2/4 dpop_info): %s", cap_info.get("url") or "")
        log.info("[MITM] 截获 URL(3/4 dpop_on_sale_list): %s", cap_on_sale.get("url") or "")
        log.info("[MITM] 截获 URL(4/4 dpop_item_get_info): %s", cap_item_get.get("url") or "")
        log.info(
            "[MITM] 本次合并 value 字段 (%d 项): %s",
            len(keys_sorted),
            ", ".join(keys_sorted),
        )
        for line in _mitm_patch_console_lines(patch):
            log.info("[MITM]%s", line)
        # print 不依赖 logging 配置，保证启动脚本控制台一定能看到
        print("\n========== [MITM] 捕获已写入账号 ==========", flush=True)
        print(f"  截获 URL(1/4 dpop_list): {cap_list.get('url') or ''}", flush=True)
        print(f"  截获 URL(2/4 dpop_info): {cap_info.get('url') or ''}", flush=True)
        print(f"  截获 URL(3/4 dpop_on_sale_list): {cap_on_sale.get('url') or ''}", flush=True)
        print(f"  截获 URL(4/4 dpop_item_get_info): {cap_item_get.get('url') or ''}", flush=True)
        print(f"  account_id={aid} seller_id={sid_cap} ts={cap_item_get.get('ts')}", flush=True)
        print(f"  字段({len(keys_sorted)}): {', '.join(keys_sorted)}", flush=True)
        for line in _mitm_patch_console_lines(patch):
            print(f"[MITM]{line}", flush=True)
        print("==========================================\n", flush=True)

        # 认证抓取流程已完成：自动关闭该账号浏览器会话，避免残留窗口。
        if cfg.open_browser and mgr is not None:
            try:
                await mgr.close_session(auto_key, force=True)
            except Exception as exc:
                log.warning("[MITM] 认证完成后自动关闭浏览器失败 id=%s: %s", aid, exc)

        return {
            "success": True,
            "data": _item_api_dict(item),
            "captured_field_keys": keys_sorted,
            "capture_meta": {**capture_meta, "seller_id": sid_cap},
            "mitm": mitm_status(),
        }
    finally:
        clear_session_marker(aid)


@router.delete("/{aid}")
def delete_meilu_account(aid: int):
    item = MeiluAccountModel.find_by_id(id=aid)
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not item.delete():
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": "删除成功"}
