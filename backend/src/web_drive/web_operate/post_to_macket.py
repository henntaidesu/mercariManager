# -*- coding: utf-8 -*-
"""
Mercari 出品自动化：打开 https://jp.mercari.com/sell/create 并填写表单。

执行步骤：
  前置  确保 Switch 开关处于 false（关闭）状态
   1.  图片上传（写真を追加）
   2.  填写商品名称
   3.  选择商品类型（按 DB position 逐级点击；若进入 /sell/wizard 则点击「出品画面に戻る」返回）
   4.  选择商品状態（#main 内按日文文案点入口与选项；选完后若进入 /sell/wizard 则点「出品画面に戻る」）
   5.  填写商品说明
   6.  选择快递費負担
   7.  选择配送方法
   8.  选择发货地址
   9.  选择最大发货天数
  10.  选择出售类型（即购 / 拍卖；拍卖时同步选时长）
  11.  填写出售价格
  12.  点击出品按钮提交；若出品成功则自动 close_session 关闭该账号浏览器
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.app_paths import backend_root_str

log = logging.getLogger(__name__)

# ───────────────────────── Mercari 出品页 XPath ──────────────────────────── #

SELL_CREATE_URL = "https://jp.mercari.com/sell/create"
# 选择商品类型后偶尔会进入向导页，需点此返回出品表单
SELL_WIZARD_BACK_TEXT = "出品画面に戻る"
# 煤炉向导页「出品画面に戻る」：优先 data-testid（版式稳定）
SELL_WIZARD_BACK_BUTTON_TESTID = "back-to-listing-button"
SELL_WIZARD_BACK_BUTTON_XPATH = '//*[@id="main"]/div[2]/div[2]/button'

# 写真ブロック内「写真を追加」按钮
PHOTO_ADD_BUTTON_XPATH = '//*[@id="main"]/form/section[1]/div/div[6]/div[2]/button'

# Switch 开关 input（需确保 aria-checked="false"）
SWITCH_INPUT_XPATH = (
    '//*[@id="main"]/form/section[1]/div/div[2]/label/div[2]/div/div/div/input'
)

# 商品名称 input
NAME_INPUT_XPATH = '//*[@id="main"]/form/section[2]/div[2]/div/div[1]/input'

# 商品说明 textarea
DESCRIPTION_TEXTAREA_XPATH = '//*[@id="main"]/form/div[1]/div/label/textarea[1]'

# カテゴリー 入口链接
CATEGORY_LINK_XPATH = '//*[@id="main"]/form/section[3]/div[2]/span/a'

# 类别页面各级列表项（a[x] 中 x 来自 DB position 字段）
CATEGORY_ITEM_XPATH_TPL = '//*[@id="main"]/a[{pos}]'

# 商品状態：入口与选项一律在 #main 内按日文文案定位（不用 XPath）
CONDITION_ENTRY_TEXTS: Tuple[str, ...] = ("商品の状態を選択する", "商品の状態")
# API status → メルカリ一覧表示文案
CONDITION_ITEM_JA: Dict[str, str] = {
    "new_unused": "新品、未使用",
    "almost_unused": "未使用に近い",
    "good": "目立った傷や汚れなし",
    "fair": "やや傷や汚れあり",
    "used": "傷や汚れあり",
}

# 快递費負担 select
SHIPPING_PAYER_SELECT_XPATH = (
    '//*[@id="main"]/form/section[4]/div[2]/div/label/div/select'
)
# select value 映射：seller(出品者負担)=2  buyer(購入者負担)=1
SHIPPING_PAYER_VALUE: Dict[str, str] = {
    "seller": "2",  # 送料込み(出品者負担)
    "buyer":  "1",  # 着払い(購入者負担)
}

# 配送方法 入口链接
SHIPPING_METHOD_LINK_XPATH = '//*[@id="main"]/form/section[4]/div[3]/span/a'

# 配送方法 选择页面各方法的 radio input XPath
SHIPPING_METHOD_XPATH: Dict[str, str] = {
    "rakuraku":    '//*[@id="main"]/div/div[1]/div[1]/div/fieldset/input',
    "yuuyu":       '//*[@id="main"]/div/div[2]/div[1]/div/fieldset/input',
    "tanome":      '//*[@id="main"]/div/div[3]/div[1]/div/fieldset/input',
    "undecided":   '/html/body/div[2]/div[2]/main/div/div[4]/div[2]/fieldset[8]/input',
    "regular_mail":'',   # 普通郵便：页面上可能无固定 XPath；留空跳过
}

# 「未定」需先点击展开的折叠区块（点击后列表展开才能显示 未定 radio）
SHIPPING_METHOD_UNDECIDED_EXPAND_XPATH = '//*[@id="main"]/div/div[4]/div'

# 配送方法选择完成后的「確認」按钮
SHIPPING_METHOD_CONFIRM_XPATH = '/html/body/div[4]/div/div/button'

# 販売タイプ — 即購（定価）（body 下绝对路径，与煤炉当前 DOM 一致）
SALE_INSTANT_RADIO_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[2]/div[1]/label/input"
)
SALE_INSTANT_PRICE_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[2]/div[2]/div[1]/div/div/input"
)

# 販売タイプ — 拍卖（オークション）
SALE_AUCTION_RADIO_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[1]/label/input"
)
SALE_AUCTION_PRICE_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[2]/div[3]/div/div/input"
)
# 拍卖时长：通常 / 三小时（与「通常」同级 div[1]/div[2]）
SALE_AUCTION_DURATION_NORMAL_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[2]/div[1]/div/div/div[1]"
)
# 拍卖时长「三小时」：点击选项区内的 svg（煤炉用图标切换）
SALE_AUCTION_DURATION_3H_XPATH = (
    "/html/body/div[2]/div[2]/main/form/section[5]/div[2]/div/div/div[1]/div[2]/div[1]/div/div/div[2]/svg"
)

# 発送までの日数 select
SHIPPING_DAYS_SELECT_XPATH = (
    '//*[@id="main"]/form/section[4]/div[5]/div/label/div/select'
)
SHIPPING_DAYS_OPTION_INDEX: Dict[str, int] = {
    "1_2_days": 2,
    "2_3_days": 3,
    "4_7_days": 4,
}

# 発送元 select
SHIPPING_FROM_SELECT_XPATH = (
    '//*[@id="main"]/form/section[4]/div[4]/div/label/div/select'
)

# ──────────────────────────── 工具函数 ──────────────────────────────────── #

def _backend_imges_root() -> str:
    """返回 backend/imges 目录的绝对路径。"""
    return os.path.join(backend_root_str(), "imges")


def _resolve_image_to_local(url_or_path: str) -> Optional[str]:
    """将图片 URL / 路径解析为本地绝对路径（供 Playwright set_input_files 使用）。"""
    s = (url_or_path or "").strip()
    if not s:
        return None

    if s.startswith("/imges/"):
        filename = s.split("/imges/", 1)[1].strip("/")
        if not filename:
            return None
        abs_path = os.path.join(_backend_imges_root(), filename)
        return abs_path if os.path.isfile(abs_path) else None

    if os.path.isabs(s):
        return s if os.path.isfile(s) else None

    if s.startswith("http://") or s.startswith("https://"):
        ext = ".jpg"
        for candidate in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            if s.lower().split("?")[0].endswith(candidate):
                ext = candidate
                break
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tf.close()
            urllib.request.urlretrieve(s, tf.name)
            return tf.name
        except Exception as exc:
            log.warning("下载图片失败 %s: %s", s, exc)
            return None

    return None


async def _react_fill_input_locator(loc: Any, value: str) -> None:
    """对已定位的 input 节点用 React 友好方式写入值（不依赖 XPath）。"""
    await loc.first.evaluate(
        """(el, val) => {
            if (!el || el.tagName !== 'INPUT') return;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(el, String(val));
            ['focus','input','change','keyup','blur'].forEach(t =>
                el.dispatchEvent(new Event(t, { bubbles: true }))
            );
        }""",
        value,
    )


async def _react_set_input(page: Any, xpath: str, value: str) -> bool:
    """
    通过 React 原生 setter + 完整事件链写入 input 值。
    返回 True 表示成功定位并写入，False 表示元素未找到（可调用方兜底）。
    """
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) return false;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            ['focus','input','change','keyup','blur'].forEach(t =>
                el.dispatchEvent(new Event(t, { bubbles: true }))
            );
            return true;
        }""",
        [xpath, value],
    )


async def _react_set_textarea(page: Any, xpath: str, value: str) -> bool:
    """通过 React 原生 setter + 完整事件链写入 textarea 值。"""
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) el = document.querySelector('textarea[name="description"]');
            if (!el) el = document.querySelector('[data-testid="input-description"] textarea');
            if (!el) return false;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            ['focus','input','change','keyup','blur'].forEach(t =>
                el.dispatchEvent(new Event(t, { bubbles: true }))
            );
            return true;
        }""",
        [xpath, value],
    )


async def _react_set_select(page: Any, xpath: str, value: str) -> bool:
    """通过原生 setter + change 事件写入 select 值。"""
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [xpath, value],
    )


# ──────────────────────────── 主函数 ────────────────────────────────────── #

def _make_listing_progress_reporter(progress_job_id: Optional[str]) -> Callable[[str, str], None]:
    """控制台 + 日志 + 可选内存进度（供前端轮询）。"""

    from ..listing_progress import set_listing_progress

    jid = (progress_job_id or "").strip() or None

    def report(step: str, label_zh: str) -> None:
        log.info("[post_to_market] step=%s %s", step, label_zh)
        print(f"[出品] {label_zh}", flush=True)
        if jid:
            set_listing_progress(jid, step, label_zh)

    return report


def _url_is_sell_wizard(url: str) -> bool:
    u = (url or "").strip().lower()
    return "sell/wizard" in u or "/sell/wizard" in u


async def _leave_sell_wizard_if_present(
    page: Any,
    *,
    element_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    若当前为 https://jp.mercari.com/sell/wizard ，点击「出品画面に戻る」返回出品表单。
    会在「选完商品类型」或「选完商品状态」等步骤后被调用（煤炉可能插入製品情報向导）。
    优先 [data-testid=back-to-listing-button]，其次 main 下固定 XPath，再文案/role 兜底。
    返回 True 表示检测到向导页并已尝试点击返回。
    """
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    if not _url_is_sell_wizard(url):
        return False
    if report:
        report("sell_wizard", "已进入出品向导页，正在点击「出品画面に戻る」…")
    log.info("[post_to_market] 检测到 sell/wizard，尝试点击「%s」", SELL_WIZARD_BACK_TEXT)
    print(f"[出品] 检测到 sell/wizard，尝试点击「{SELL_WIZARD_BACK_TEXT}」", flush=True)
    try:
        candidates: List[Tuple[str, Any]] = [
            (
                "data-testid",
                page.locator(f'[data-testid="{SELL_WIZARD_BACK_BUTTON_TESTID}"]'),
            ),
            ("xpath_main_div2_button", page.locator(f"xpath={SELL_WIZARD_BACK_BUTTON_XPATH}")),
            ("role_button", page.get_by_role("button", name=SELL_WIZARD_BACK_TEXT)),
            ("role_link", page.get_by_role("link", name=SELL_WIZARD_BACK_TEXT)),
        ]
        clicked = False
        for tag, loc in candidates:
            try:
                cnt = await loc.count()
                if cnt < 1:
                    continue
                await loc.first.wait_for(state="visible", timeout=element_timeout_ms)
                await loc.first.scroll_into_view_if_needed()
                await loc.first.click(timeout=element_timeout_ms)
                log.info("[post_to_market] 已通过 %s 点击「%s」", tag, SELL_WIZARD_BACK_TEXT)
                clicked = True
                break
            except Exception as exc:
                log.info("[post_to_market] 向导返回按钮 %s 定位/点击失败: %s", tag, exc)
                continue
        if not clicked:
            alt = page.locator(
                f'button:has-text("{SELL_WIZARD_BACK_TEXT}"), '
                f'a:has-text("{SELL_WIZARD_BACK_TEXT}")'
            )
            await alt.first.wait_for(state="visible", timeout=element_timeout_ms)
            await alt.first.scroll_into_view_if_needed()
            await alt.first.click(timeout=element_timeout_ms)
            log.info("[post_to_market] 已通过 :has-text 点击「%s」", SELL_WIZARD_BACK_TEXT)
        await asyncio.sleep(0.45)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        log.info("[post_to_market] 已点击「%s」，当前 URL=%s", SELL_WIZARD_BACK_TEXT, page.url)
        print(f"[出品] 已返回出品画面，URL={page.url}", flush=True)
        if report:
            report("sell_wizard_done", "已从向导返回出品表单")
        return True
    except Exception as exc:
        log.warning("[post_to_market] 点击「%s」失败: %s", SELL_WIZARD_BACK_TEXT, exc)
        print(f"[出品] 点击「{SELL_WIZARD_BACK_TEXT}」失败: {exc}", flush=True)
        if report:
            report("sell_wizard_error", f"点击「{SELL_WIZARD_BACK_TEXT}」失败，请手动返回")
        return True


async def post_to_market(
    manager: Any,
    account_key: str,
    *,
    name: str = "",
    description: str = "",
    image_urls: Sequence[str] = (),
    # 类别（来自 product_type_category_mappings 表的 position 字段）
    category_level1_pos: Optional[int] = None,
    category_level2_pos: Optional[int] = None,
    category_level3_pos: Optional[int] = None,
    product_type_pos: Optional[int] = None,
    # 商品状態：new_unused / almost_unused / good / fair / used
    status: str = "",
    # 快递費負担：seller(出品者負担) / buyer(購入者負担)
    shipping_payer: str = "seller",
    # 配送方法：undecided / rakuraku / yuuyu / tanome / regular_mail
    shipping_method: str = "undecided",
    # 販売タイプ + 价格
    sale_type: str = "instant_buy",   # "instant_buy" | "auction"
    auction_duration: str = "normal",  # "normal" | "3hours"（仅 auction 时生效）
    price: int = 0,
    # 发货
    shipping_days: str = "2_3_days",  # "1_2_days" | "2_3_days" | "4_7_days"
    shipping_from_area_id: str = "",  # "1"~"47","99"
    # 代理 / 超时
    proxy_server: Optional[str] = None,
    page_load_timeout_ms: int = 30_000,
    element_timeout_ms: int = 20_000,
    # 可选：与 GET /listing/post-progress/{id} 配合，前端轮询展示步骤
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    自动填写 Mercari 出品表单的全部步骤。
    """
    from ..manager import EdgeWebDriveManager

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    progress_key = (progress_job_id or "").strip() or None
    report = _make_listing_progress_reporter(progress_key)

    # ── 解析代理地址 ─────────────────────────────────────────────────────── #
    ps = (proxy_server or "").strip()
    if not ps:
        try:
            from ...ssl_mitm_proxy.runner import default_mitm_proxy_url
            ps = default_mitm_proxy_url()
        except Exception:
            ps = "http://127.0.0.1:8890"

    # ── 解析图片为本地路径 ───────────────────────────────────────────────── #
    local_images: List[str] = []
    for u in image_urls:
        p = _resolve_image_to_local(u)
        if p:
            local_images.append(p)
        else:
            log.warning("无法解析图片路径，跳过: %s", u)

    report("open_session", "正在启动浏览器并打开出品页…")
    # ── 1. 启动/复用会话并导航到出品页 ──────────────────────────────────── #
    await manager.open_session(
        account_key,
        headless=False,
        start_url=SELL_CREATE_URL,
        proxy_server=ps,
        interactive=True,
    )

    s = manager._prepare_async()
    async with s.lock:  # type: ignore[union-attr]
        ctx = s.contexts.get(account_key)
        if ctx is None or not manager._is_context_alive(ctx):
            raise RuntimeError(f"会话启动失败: {account_key}")
        page = ctx.pages[-1] if ctx.pages else await ctx.new_page()

    # ── 2. 等待页面可交互 ────────────────────────────────────────────────── #
    report("page_load", "等待出品页加载完成…")
    try:
        await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
        except Exception:
            pass

    result: Dict[str, Any] = {
        "account_key": account_key,
        "url": page.url,
        "switch_checked": None,
        "switch_clicked": False,
        "images_uploaded": 0,
        "name_filled": False,
        "category_selected": False,
        "sell_wizard_back_clicked": False,
        "condition_set": False,
        "description_filled": False,
        "shipping_payer_set": False,
        "shipping_method_set": False,
        "shipping_from_set": False,
        "shipping_days_set": False,
        "sale_type_set": False,
        "price_filled": False,
        "submitted": False,
    }

    # ── 前置：确保 Switch 开关处于 false ─────────────────────────────────── #
    report("switch", "检查出品页 Switch 开关状态…")
    try:
        switch_loc = page.locator(f"xpath={SWITCH_INPUT_XPATH}")
        await switch_loc.first.wait_for(state="attached", timeout=element_timeout_ms)
        aria_checked = await switch_loc.first.get_attribute("aria-checked")
        result["switch_checked"] = aria_checked
        if (aria_checked or "").lower() == "true":
            label_loc = page.locator(
                'xpath=//*[@id="main"]/form/section[1]/div/div[2]/label'
            )
            await label_loc.first.click(timeout=element_timeout_ms)
            result["switch_clicked"] = True
            try:
                await page.wait_for_function(
                    """(xpath) => {
                        const el = document.evaluate(xpath, document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        return el && el.getAttribute('aria-checked') !== 'true';
                    }""",
                    SWITCH_INPUT_XPATH,
                    timeout=5_000,
                )
            except Exception:
                pass
    except Exception as exc:
        log.warning("[post_to_market] Switch 检查失败: %s", exc)
        result["switch_error"] = str(exc)

    # ── 步骤 1：图片上传 ──────────────────────────────────────────────────── #
    if local_images:
        report("upload_images", f"正在上传商品图片（{len(local_images)} 张）…")
        try:
            btn_loc = page.locator(f"xpath={PHOTO_ADD_BUTTON_XPATH}")
            await btn_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            async with page.expect_file_chooser(timeout=element_timeout_ms) as fc_info:
                await btn_loc.first.click()
            fc = await fc_info.value
            await fc.set_files(local_images)
            result["images_uploaded"] = len(local_images)
            try:
                await page.wait_for_selector(
                    "img[alt*='写真'], img[alt*='photo'], section img",
                    timeout=10_000,
                )
            except Exception:
                pass
            # 关闭图像选择弹窗（暂时注释，弹窗可能已自动关闭或 XPath 需确认）
            # try:
            #     close_btn = page.locator('xpath=//*[@id="modal"]/div[3]/div/button')
            #     await close_btn.first.wait_for(state="visible", timeout=element_timeout_ms)
            #     await close_btn.first.click()
            #     try:
            #         await close_btn.first.wait_for(state="hidden", timeout=5_000)
            #     except Exception:
            #         pass
            # except Exception as exc:
            #     log.warning("[post_to_market] 关闭图像弹窗失败: %s", exc)
            #     result["modal_close_warning"] = str(exc)
        except Exception as exc:
            log.error("[post_to_market] 图片上传失败: %s", exc)
            result["images_error"] = str(exc)

    # ── 步骤 2：填写商品名称 ──────────────────────────────────────────────── #
    name_str = (name or "").strip()
    if name_str:
        report("name", "正在填写商品名称…")
        try:
            name_loc = page.locator(f"xpath={NAME_INPUT_XPATH}").or_(
                page.locator('input[name="name"]')
            ).or_(page.locator('[data-testid="input-name"] input'))
            await name_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            await name_loc.first.scroll_into_view_if_needed()
            await name_loc.first.click()
            await page.wait_for_timeout(100)
            filled = await _react_set_input(page, NAME_INPUT_XPATH, name_str)
            if not filled:
                await name_loc.first.focus()
                await page.keyboard.press("Control+a")
                await page.keyboard.type(name_str, delay=0)
            result["name_filled"] = True
        except Exception as exc:
            log.error("[post_to_market] 填写商品名称失败: %s", exc)
            result["name_error"] = str(exc)

    # ── 步骤 3：选择商品类型 ──────────────────────────────────────────────── #
    if any(p is not None for p in [
        category_level1_pos, category_level2_pos,
        category_level3_pos, product_type_pos,
    ]):
        try:
            wizard_back = await _select_category(
                page,
                category_level1_pos,
                category_level2_pos,
                category_level3_pos,
                product_type_pos,
                element_timeout_ms=element_timeout_ms,
                page_load_timeout_ms=page_load_timeout_ms,
                report=report,
            )
            result["category_selected"] = True
            result["sell_wizard_back_clicked"] = bool(wizard_back)
        except Exception as exc:
            log.error("[post_to_market] 商品类型选择失败: %s", exc)
            result["category_error"] = str(exc)

    # ── 步骤 4：选择商品状態 ──────────────────────────────────────────────── #
    if status:
        report("condition", "正在选择商品状态…")
        try:
            await _select_condition(
                page,
                status,
                element_timeout_ms=element_timeout_ms,
                page_load_timeout_ms=page_load_timeout_ms,
                report=report,
            )
            result["condition_set"] = True
        except Exception as exc:
            log.error("[post_to_market] 商品状態選択失败: %s", exc)
            result["condition_error"] = str(exc)

    # ── 步骤 5：填写商品说明 ──────────────────────────────────────────────── #
    desc_str = (description or "").strip()
    if desc_str:
        report("description", "正在填写商品说明…")
        try:
            desc_loc = page.locator(f"xpath={DESCRIPTION_TEXTAREA_XPATH}").or_(
                page.locator('textarea[name="description"]')
            ).or_(page.locator('[data-testid="input-description"] textarea'))
            await desc_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            await desc_loc.first.scroll_into_view_if_needed()
            await desc_loc.first.click()
            await page.wait_for_timeout(150)
            filled = await _react_set_textarea(page, DESCRIPTION_TEXTAREA_XPATH, desc_str)
            if not filled:
                await desc_loc.first.focus()
                await page.keyboard.press("Control+a")
                await page.keyboard.type(desc_str, delay=0)
            result["description_filled"] = True
        except Exception as exc:
            log.error("[post_to_market] 填写商品说明失败: %s", exc)
            result["description_error"] = str(exc)

    # ── 步骤 6：选择快递費負担 ────────────────────────────────────────────── #
    if shipping_payer:
        report("shipping_payer", "正在设置配送费负担…")
        try:
            await _set_shipping_payer(
                page, shipping_payer,
                element_timeout_ms=element_timeout_ms,
            )
            result["shipping_payer_set"] = True
        except Exception as exc:
            log.error("[post_to_market] 快递費負担设置失败: %s", exc)
            result["shipping_payer_error"] = str(exc)

    # ── 步骤 7：选择配送方法 ──────────────────────────────────────────────── #
    if shipping_method:
        report("shipping_method", "正在选择配送方法…")
        try:
            await _select_shipping_method(
                page, shipping_method,
                element_timeout_ms=element_timeout_ms,
                page_load_timeout_ms=page_load_timeout_ms,
            )
            result["shipping_method_set"] = True
        except Exception as exc:
            log.error("[post_to_market] 配送方法设置失败: %s", exc)
            result["shipping_method_error"] = str(exc)

    # ── 步骤 8：选择发货地址 ──────────────────────────────────────────────── #
    if shipping_from_area_id:
        report("shipping_from", "正在选择发货地址…")
        try:
            await _set_shipping_from(
                page, shipping_from_area_id,
                element_timeout_ms=element_timeout_ms,
            )
            result["shipping_from_set"] = True
        except Exception as exc:
            log.error("[post_to_market] 发货地址设置失败: %s", exc)
            result["shipping_from_error"] = str(exc)

    # ── 步骤 9：选择最大发货天数 ──────────────────────────────────────────── #
    if shipping_days:
        report("shipping_days", "正在选择发货天数…")
        try:
            await _set_shipping_days(
                page, shipping_days,
                element_timeout_ms=element_timeout_ms,
            )
            result["shipping_days_set"] = True
        except Exception as exc:
            log.error("[post_to_market] 发货天数设置失败: %s", exc)
            result["shipping_days_error"] = str(exc)

    # ── 步骤 10+11：选择出售类型 + 填写价格 ──────────────────────────────── #
    report("sale_price", "正在设置销售方式与价格…")
    try:
        await _set_sale_type_and_price(
            page,
            sale_type,
            price,
            auction_duration=auction_duration,
            element_timeout_ms=element_timeout_ms,
            report=report,
        )
        result["sale_type_set"] = True
        result["price_filled"] = True
    except Exception as exc:
        log.error("[post_to_market] 销售类型/价格设置失败: %s", exc)
        result["sale_price_error"] = str(exc)

    # ── 步骤 12：点击出品（出售）按钮 ───────────────────────────────────── #
    report("submit", "正在点击出品按钮提交…")
    try:
        submit_loc = page.locator('xpath=//*[@id="main"]/form/div[3]/div[1]/button')
        await submit_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
        await submit_loc.first.scroll_into_view_if_needed()
        await submit_loc.first.click()
        log.info("[post_to_market] 已点击出品按钮，等待页面跳转…")

        # 等待跳转到 https://jp.mercari.com/sell
        try:
            await page.wait_for_url(
                "**/sell**",
                timeout=30_000,
            )
        except Exception:
            pass

        result["url_after_submit"] = page.url

        # 检查出品完成提示文本
        SUCCESS_TEXT = "出品が完了しました"
        CONFIRM_SPAN_XPATH = (
            '/html/body/div[4]/div/div[2]/div[2]/div/div[1]/span'
        )
        try:
            span_loc = page.locator(f"xpath={CONFIRM_SPAN_XPATH}")
            await span_loc.first.wait_for(state="visible", timeout=10_000)
            span_text = (await span_loc.first.inner_text()).strip()
            result["submit_message"] = span_text
            if span_text == SUCCESS_TEXT:
                result["submitted"] = True
                log.info("[post_to_market] 出品成功：%s", span_text)
            else:
                result["submitted"] = False
                log.warning("[post_to_market] 出品提示文本异常: %s", span_text)
        except Exception as exc:
            # 找不到提示框时以页面 URL 判断是否跳转成功
            log.warning("[post_to_market] 未找到出品完成提示框: %s", exc)
            result["submit_message"] = ""
            result["submitted"] = "sell" in page.url
    except Exception as exc:
        log.error("[post_to_market] 点击出品按钮失败: %s", exc)
        result["submit_error"] = str(exc)

    # 出品成功：关闭该账号 WebDriver 浏览器（释放 profile，下次再开干净会话）
    if result.get("submitted") is True:
        if report:
            report("close_browser", "出品成功，正在关闭浏览器…")
        try:
            await manager.close_session(account_key, force=True)
            result["browser_closed"] = True
            log.info("[post_to_market] 出品成功，已关闭浏览器会话: %s", account_key)
            print(f"[出品] 出品成功，已关闭浏览器: {account_key}", flush=True)
        except Exception as exc:
            result["browser_closed"] = False
            result["browser_close_error"] = str(exc)
            log.warning("[post_to_market] 出品成功后关闭浏览器失败: %s", exc)

    return result


# ──────────────────────── 子步骤实现 ────────────────────────────────────── #

async def _select_category(
    page: Any,
    level1_pos: Optional[int],
    level2_pos: Optional[int],
    level3_pos: Optional[int],
    product_type_pos: Optional[int],
    *,
    element_timeout_ms: int,
    page_load_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    点击商品类型入口 → 依次按各级 position（1-based a[x]）在类别页面中导航并点击。
    Mercari 类别选择页面每次点击都会刷新列表，需等待新内容出现。
    若进入 sell/wizard，尝试点击「出品画面に戻る」；返回是否检测到向导页并已尝试返回。
    """
    if report:
        report("category", "正在选择商品类型（カテゴリー）…")
    # 点击表单内的「カテゴリー」链接，进入类别选择页面
    cat_link = page.locator(f"xpath={CATEGORY_LINK_XPATH}")
    await cat_link.first.wait_for(state="visible", timeout=element_timeout_ms)
    await cat_link.first.click()
    await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)

    # 按层级依次点击
    levels = [
        ("level1", level1_pos),
        ("level2", level2_pos),
        ("level3", level3_pos),
        ("product_type", product_type_pos),
    ]
    for level_name, pos in levels:
        if pos is None:
            continue
        xpath = CATEGORY_ITEM_XPATH_TPL.format(pos=pos)
        loc = page.locator(f"xpath={xpath}")
        try:
            await loc.first.wait_for(state="visible", timeout=element_timeout_ms)
        except Exception:
            # 该层级可能不存在（如只有2级），跳过
            log.info("[category] %s pos=%s 元素未出现，跳过", level_name, pos)
            continue
        await loc.first.click()
        log.info("[category] 已点击 %s pos=%s", level_name, pos)
        # 等待页面更新（下一级列表或返回表单）
        await asyncio.sleep(0.5)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
        except Exception:
            pass

    # 最后一级点击后，向导页可能异步出现；稍等 pathname 再检测 wizard
    await asyncio.sleep(0.4)
    try:
        await page.wait_for_function(
            """() => {
                const p = location.pathname || '';
                const href = location.href || '';
                return href.includes('sell/wizard') || p.includes('/sell/wizard')
                    || href.includes('sell/create') || p.includes('/sell/create');
            }""",
            timeout=min(22_000, page_load_timeout_ms),
        )
    except Exception:
        log.info("[category] 等待进入 sell/create 或 sell/wizard 超时，仍尝试关闭向导")

    return await _leave_sell_wizard_if_present(
        page,
        element_timeout_ms=element_timeout_ms,
        report=report,
    )


async def _pick_visible_price_locator(
    page: Any,
    price_xpath: str,
    *,
    element_timeout_ms: int,
) -> Any:
    """
    販売価格 input：主 XPath 易随版式失效，依次尝试多种选择器。
    """
    per = min(10_000, max(4_000, element_timeout_ms // 2))
    candidates: List[Any] = [
        page.locator(f"xpath={price_xpath}"),
        page.locator('#main input[name="price"]'),
        page.locator('[data-testid="input-price"] input'),
        page.locator('[data-testid="price-input"] input'),
        page.get_by_placeholder(re.compile(r"半角|数字|円", re.I)),
    ]
    last_exc: Optional[BaseException] = None
    for loc in candidates:
        try:
            await loc.first.wait_for(state="visible", timeout=per)
            return loc
        except Exception as exc:
            last_exc = exc
            continue
    # 兜底：表单内靠后的数字输入（出品价通常在页面中下部）
    try:
        loc = page.locator('#main form input[inputmode="numeric"]').last
        await loc.wait_for(state="visible", timeout=per)
        return loc
    except Exception as exc:
        last_exc = exc
    if last_exc:
        raise last_exc
    raise RuntimeError("未找到販売価格输入框")


async def _set_sale_type_and_price(
    page: Any,
    sale_type: str,
    price: int,
    *,
    auction_duration: str = "normal",
    element_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> None:
    """
    选择販売タイプ（即购 / 拍卖）并填写价格。
    拍卖时额外点击时长选项（通常 / 三小时）。
    """
    await _leave_sell_wizard_if_present(
        page,
        element_timeout_ms=min(15_000, element_timeout_ms),
        report=report,
    )

    is_instant = (sale_type or "instant_buy") == "instant_buy"
    radio_xpath = SALE_INSTANT_RADIO_XPATH if is_instant else SALE_AUCTION_RADIO_XPATH
    price_xpath = SALE_INSTANT_PRICE_XPATH if is_instant else SALE_AUCTION_PRICE_XPATH

    try:
        main_form = page.locator("#main")
        await main_form.first.wait_for(state="attached", timeout=element_timeout_ms)
        await main_form.first.scroll_into_view_if_needed()
    except Exception:
        pass

    # 点击 radio（主 XPath + 文案兜底）
    radio_loc = page.locator(f"xpath={radio_xpath}")
    try:
        await radio_loc.first.wait_for(state="attached", timeout=min(12_000, element_timeout_ms))
        await radio_loc.first.scroll_into_view_if_needed()
        await radio_loc.first.click(timeout=element_timeout_ms, force=True)
    except Exception:
        log.info("[sale] 主 XPath 点 radio 失败，尝试即购/拍卖文案")
        try:
            if is_instant:
                alt = page.locator("#main label").filter(has_text=re.compile(r"即購|定価|すぐ購入", re.I)).locator("input").first
            else:
                alt = page.locator("#main label").filter(has_text=re.compile(r"オークション|競り", re.I)).locator("input").first
            await alt.wait_for(state="attached", timeout=min(12_000, element_timeout_ms))
            await alt.scroll_into_view_if_needed()
            await alt.click(timeout=element_timeout_ms, force=True)
        except Exception as exc:
            log.warning("[sale] radio 兜底失败: %s", exc)
    await page.wait_for_timeout(250)

    # 拍卖时选择时长（通常 / 三小时）
    if not is_instant:
        duration_xpath = (
            SALE_AUCTION_DURATION_3H_XPATH
            if (auction_duration or "normal") == "3hours"
            else SALE_AUCTION_DURATION_NORMAL_XPATH
        )
        try:
            dur_loc = page.locator(f"xpath={duration_xpath}")
            await dur_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            await dur_loc.first.scroll_into_view_if_needed()
            await dur_loc.first.click(timeout=element_timeout_ms)
            log.info("[sale] 拍卖时长已选: %s", auction_duration)
            await page.wait_for_timeout(200)
        except Exception as exc:
            log.warning("[sale] 拍卖时长选择失败: %s", exc)

    # 填写价格（多选择器 + evaluate 写入）
    price_str = str(max(0, int(price)))
    price_loc = await _pick_visible_price_locator(
        page, price_xpath, element_timeout_ms=element_timeout_ms
    )
    await price_loc.first.scroll_into_view_if_needed()
    await price_loc.first.click(timeout=element_timeout_ms)
    await page.wait_for_timeout(120)
    try:
        await _react_fill_input_locator(price_loc, price_str)
    except Exception as exc:
        log.info("[sale] evaluate 写入价格失败，尝试 XPath/React: %s", exc)
    filled = await _react_set_input(page, price_xpath, price_str)
    if not filled:
        try:
            await _react_fill_input_locator(price_loc, price_str)
        except Exception:
            await price_loc.first.focus()
            await page.keyboard.press("Control+a")
            await page.keyboard.type(price_str, delay=0)
    log.info("[sale] type=%s duration=%s price=%s 已设置", sale_type, auction_duration, price_str)


async def _set_shipping_days(
    page: Any,
    shipping_days: str,
    *,
    element_timeout_ms: int,
) -> None:
    """
    选择「発送までの日数」select。
    option[2]=1~2日  option[3]=2~3日  option[4]=4~7日
    """
    opt_index = SHIPPING_DAYS_OPTION_INDEX.get(shipping_days)
    if opt_index is None:
        log.warning("[shipping_days] 未知的值: %s，跳过", shipping_days)
        return

    select_loc = page.locator(f"xpath={SHIPPING_DAYS_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await select_loc.first.scroll_into_view_if_needed()

    # 先尝试 Playwright select_option（by index）
    try:
        # Playwright index 是 0-based；XPath option[2] 对应 index=1
        await select_loc.first.select_option(index=opt_index - 1, timeout=element_timeout_ms)
        log.info("[shipping_days] 已选 option[%s] (%s)", opt_index, shipping_days)
        return
    except Exception:
        pass

    # 兜底：JavaScript 通过 option value 设置
    opt_xpath = f"{SHIPPING_DAYS_SELECT_XPATH}/option[{opt_index}]"
    opt_value = await page.evaluate(
        """(xpath) => {
            const el = document.evaluate(xpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            return el ? el.value : null;
        }""",
        opt_xpath,
    )
    if opt_value is not None:
        await _react_set_select(page, SHIPPING_DAYS_SELECT_XPATH, str(opt_value))
        log.info("[shipping_days] JS设置 option value=%s", opt_value)


async def _set_shipping_from(
    page: Any,
    area_id: str,
    *,
    element_timeout_ms: int,
) -> None:
    """
    选择「発送元」select。
    select 的 option value 与 Mercari areas[].id 一致（纯数字字符串）。
    """
    aid = str(area_id).strip()
    if not aid:
        return

    select_loc = page.locator(f"xpath={SHIPPING_FROM_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await select_loc.first.scroll_into_view_if_needed()

    # 先尝试 Playwright select_option（by value）
    try:
        await select_loc.first.select_option(value=aid, timeout=element_timeout_ms)
        log.info("[shipping_from] 已选 area_id=%s", aid)
        return
    except Exception:
        pass

    # 兜底：JavaScript
    await _react_set_select(page, SHIPPING_FROM_SELECT_XPATH, aid)
    log.info("[shipping_from] JS设置 area_id=%s", aid)


# ─────────────── 商品状態 / 快递費負担 / 配送方法 子步骤 ─────────────────── #

async def _select_condition(
    page: Any,
    status: str,
    *,
    element_timeout_ms: int,
    page_load_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> None:
    """
    点击 #main 内「商品の状態…」入口 → 在列表页按日文选项文案点选。
    选完选项后有时会进入 /sell/wizard，须再点「出品画面に戻る」。
    """
    ja_label = CONDITION_ITEM_JA.get(status)
    if not ja_label:
        log.warning("[condition] 未知状态值: %s，跳过", status)
        return

    # 若类型选完后仍停留在 sell/wizard，先返回出品表单再点状态入口
    await _leave_sell_wizard_if_present(
        page,
        element_timeout_ms=element_timeout_ms,
        report=report,
    )

    # 入口：#main 内 a / button / 可点 span，按文案（长文案优先）
    main = page.locator("#main")
    last_exc: Optional[BaseException] = None
    clicked = False
    for text in CONDITION_ENTRY_TEXTS:
        try:
            loc = main.locator("a, button, [role='button'], span").filter(has_text=text).first
            await loc.wait_for(state="visible", timeout=element_timeout_ms)
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=element_timeout_ms)
            clicked = True
            log.info("[condition] 已通过文案「%s」打开商品状态", text)
            break
        except Exception as exc:
            last_exc = exc
            continue
    if not clicked:
        for text in CONDITION_ENTRY_TEXTS:
            try:
                loc = main.get_by_text(text, exact=False).first
                await loc.wait_for(state="visible", timeout=element_timeout_ms)
                await loc.click(timeout=element_timeout_ms)
                clicked = True
                log.info("[condition] get_by_text「%s」打开商品状态", text)
                break
            except Exception as exc:
                last_exc = exc
                continue
    if not clicked:
        raise last_exc if last_exc else RuntimeError("未找到商品状态入口文案")

    await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)

    # 列表页：按日文状态文案点选（优先 #main，失败则全页）
    row_sel = "li, button, [role='option'], [role='radio'], label, div[role='button']"
    try:
        item = main.locator(row_sel).filter(has_text=ja_label).first
        await item.wait_for(state="visible", timeout=element_timeout_ms)
    except Exception:
        item = page.locator(row_sel).filter(has_text=ja_label).first
        await item.wait_for(state="visible", timeout=element_timeout_ms)
    await item.scroll_into_view_if_needed()
    await item.click(timeout=element_timeout_ms)
    log.info("[condition] 已选 status=%s 文案=%s", status, ja_label)

    # 等待返回表单页（或异步跳转到 sell/wizard）
    await asyncio.sleep(0.5)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
    except Exception:
        pass

    await asyncio.sleep(0.4)
    try:
        await page.wait_for_function(
            """() => {
                const p = location.pathname || '';
                const href = location.href || '';
                return href.includes('sell/wizard') || p.includes('/sell/wizard')
                    || href.includes('sell/create') || p.includes('/sell/create');
            }""",
            timeout=min(22_000, page_load_timeout_ms),
        )
    except Exception:
        log.info("[condition] 选择后等待路径进入 create 或 wizard 超时，仍检测向导页")

    await _leave_sell_wizard_if_present(
        page,
        element_timeout_ms=element_timeout_ms,
        report=report,
    )


async def _set_shipping_payer(
    page: Any,
    shipping_payer: str,
    *,
    element_timeout_ms: int,
) -> None:
    """
    选择「配送料の負担」select。
    seller → value "2"（送料込み / 出品者負担）
    buyer  → value "1"（着払い / 購入者負担）
    """
    value = SHIPPING_PAYER_VALUE.get(shipping_payer)
    if value is None:
        log.warning("[shipping_payer] 未知值: %s，跳过", shipping_payer)
        return

    select_loc = page.locator(f"xpath={SHIPPING_PAYER_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await select_loc.first.scroll_into_view_if_needed()

    try:
        await select_loc.first.select_option(value=value, timeout=element_timeout_ms)
        log.info("[shipping_payer] 已选 %s (value=%s)", shipping_payer, value)
        return
    except Exception:
        pass

    # 兜底：JavaScript
    await _react_set_select(page, SHIPPING_PAYER_SELECT_XPATH, value)
    log.info("[shipping_payer] JS设置 value=%s", value)


async def _select_shipping_method(
    page: Any,
    shipping_method: str,
    *,
    element_timeout_ms: int,
    page_load_timeout_ms: int,
) -> None:
    """
    点击配送方法入口链接 → 在新页面中点击对应 radio → 点击确认按钮。

    支持方法：
      undecided   → 未定
      rakuraku    → らくらくメルカリ便
      yuuyu       → ゆうゆうメルカリ便
      tanome      → 梱包・発送たのメル便
      regular_mail→ 跳过（XPath 未确认）
    """
    radio_xpath = SHIPPING_METHOD_XPATH.get(shipping_method, "")
    if not radio_xpath:
        log.warning("[shipping_method] 未知或未支持方法: %s，跳过", shipping_method)
        return

    # 点击表单内的「配送の方法」链接
    link_loc = page.locator(f"xpath={SHIPPING_METHOD_LINK_XPATH}")
    await link_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await link_loc.first.click()
    await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)

    # 若选择「未定」，需先点击折叠标题展开选项列表
    if shipping_method == "undecided":
        expand_loc = page.locator(f"xpath={SHIPPING_METHOD_UNDECIDED_EXPAND_XPATH}")
        try:
            await expand_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            await expand_loc.first.click()
            log.info("[shipping_method] 已展开「未定」选项组")
            await page.wait_for_timeout(400)
        except Exception as exc:
            log.warning("[shipping_method] 展开「未定」折叠失败: %s", exc)

    # 点击 radio
    radio_loc = page.locator(f"xpath={radio_xpath}")
    await radio_loc.first.wait_for(state="attached", timeout=element_timeout_ms)
    await radio_loc.first.scroll_into_view_if_needed()
    try:
        await radio_loc.first.click(force=True, timeout=element_timeout_ms)
    except Exception:
        pass
    log.info("[shipping_method] 已选 %s", shipping_method)
    await page.wait_for_timeout(300)

    # 点击确认按钮
    confirm_loc = page.locator(f"xpath={SHIPPING_METHOD_CONFIRM_XPATH}")
    try:
        await confirm_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
        await confirm_loc.first.click()
        log.info("[shipping_method] 已点击确认按钮")
    except Exception as exc:
        log.warning("[shipping_method] 确认按钮点击失败: %s", exc)

    # 等待返回表单页
    await asyncio.sleep(0.5)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
    except Exception:
        pass
