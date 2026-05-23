# -*- coding: utf-8 -*-
"""
监控 Mercari 关键接口请求，将头与查询参数写入配置文件。

配置文件：backend/ssl_mitm/items_get_items_capture.json（由 mitm 插件原子写入）
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from .paths import ssl_mitm_data_dir

_lock = threading.Lock()

# 与 meilu 账号 value 中字段名一致（DPoP 字段按接口类型动态映射）
HEADER_MAP_TO_VALUE = (
    ("authorization", "authorization"),
    ("user-agent", "user_agent"),
    ("accept", "accept"),
    ("accept-language", "accept_language"),
    ("accept-encoding", "accept_encoding"),
    ("priority", "priority"),
    ("x-platform", "x_platform"),
    ("x-app-version", "x_app_version"),
    ("sec-ch-ua", "sec_ch_ua"),
    ("sec-ch-ua-mobile", "sec_ch_ua_mobile"),
    ("sec-ch-ua-platform", "sec_ch_ua_platform"),
    ("origin", "origin"),
    ("referer", "referer"),
    ("sec-fetch-site", "sec_fetch_site"),
    ("sec-fetch-mode", "sec_fetch_mode"),
    ("sec-fetch-dest", "sec_fetch_dest"),
)


def capture_json_path(capture_type: str = "") -> str:
    """每种 capture_type 对应独立文件，避免并发请求互相覆盖。"""
    name = f"capture_{capture_type}.json" if capture_type else "items_get_items_capture.json"
    return os.path.join(ssl_mitm_data_dir(), name)


def session_marker_path(account_id: int) -> str:
    return os.path.join(ssl_mitm_data_dir(), f"capture_marker_{account_id}.txt")


def write_session_marker_ms(account_id: int, ts_ms: int) -> None:
    os.makedirs(ssl_mitm_data_dir(), exist_ok=True)
    p = session_marker_path(account_id)
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(ts_ms))


def read_session_marker_ms(account_id: int) -> Optional[int]:
    p = session_marker_path(account_id)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return int((f.read() or "0").strip())
    except (ValueError, OSError):
        return None


def clear_session_marker(account_id: int) -> None:
    p = session_marker_path(account_id)
    try:
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass


def parse_capture_target(
    flow_url: str, path: str, host: str, raw_query: str = "", method: str = ""
) -> Optional[Dict[str, Any]]:
    """匹配关键接口并提取元信息。

    - ``GET /items/get_items``: 提取 seller_id + status（用于 dpop_list / dpop_on_sale_list）
    - ``GET /transaction_evidences/get``: 提取 item_id（用于 dpop_info）
    - ``GET /items/get``: 提取 item_id（用于 dpop_item_get_info）
    - ``POST /services/todolist/v1/list``: 代办事项列表（POST，无 query）
    """
    try:
        m = (method or "").strip().upper()
        h = (host or "").lower().strip()
        pth = (path or "").split("?", 1)[0]
        u = (flow_url or "").strip()
        if not u.startswith("http"):
            q = f"?{raw_query}" if raw_query else ""
            u = f"https://{h}{pth}{q}"
        parsed = urlparse(u)
        if parsed.netloc.lower() != "api.mercari.jp":
            return None
        norm_path = (parsed.path or "").rstrip("/")
        qd = parse_qs(parsed.query)
        if m and m != "GET" and not norm_path.endswith("services/todolist/v1/list"):
            return None
        if norm_path.endswith("items/get_items"):
            sid_list = qd.get("seller_id") or qd.get("sellerId") or []
            sid = (sid_list[0] or "").strip() if sid_list else ""
            # status 可能是多值（?status=on_sale&status=stop）也可能是逗号分隔（?status=on_sale,stop）
            status_vals: List[str] = []
            for raw_s in qd.get("status", []):
                for part in (raw_s or "").split(","):
                    part = part.strip().lower()
                    if part:
                        status_vals.append(part)
            if not sid.isdigit():
                return None
            if not status_vals:
                return None
            dpop_field = "dpop_on_sale_list" if any(s in ("on_sale", "stop") for s in status_vals) else "dpop_list"
            return {
                "capture_type": "items_get_items",
                "seller_id": sid,
                "status_values": status_vals,
                "http_method": "GET",
                "dpop_field": dpop_field,
                "full_url": u,
            }
        if norm_path.endswith("transaction_evidences/get"):
            item_list = qd.get("item_id") or qd.get("itemId") or qd.get("id") or []
            item_id = (item_list[0] or "").strip() if item_list else ""
            return {
                "capture_type": "transaction_evidences_get",
                "item_id": item_id,
                "http_method": "GET",
                "dpop_field": "dpop_info",
                "full_url": u,
            }
        if norm_path.endswith("items/get"):
            item_list = qd.get("id") or qd.get("item_id") or qd.get("itemId") or []
            item_id = (item_list[0] or "").strip() if item_list else ""
            if not item_id:
                return None
            return {
                "capture_type": "items_get",
                "item_id": item_id,
                "http_method": "GET",
                "dpop_field": "dpop_item_get_info",
                "full_url": u,
            }
        if norm_path.endswith("services/todolist/v1/list"):
            return {
                "capture_type": "todolist_list",
                "http_method": m or "POST",
                "dpop_field": "dpop_todolist",
                "full_url": u,
            }
        return None
    except Exception:
        return None


def headers_to_value_dict(flow_headers: Any, dpop_field: str = "dpop_list") -> Dict[str, str]:
    out: Dict[str, str] = {}
    dpop_val = ""
    for dkey in ("dpop", "dpop-list"):
        raw_dpop = None
        try:
            raw_dpop = flow_headers.get(dkey)
        except Exception:
            raw_dpop = None
        if raw_dpop is None:
            continue
        if isinstance(raw_dpop, bytes):
            raw_dpop = raw_dpop.decode("utf-8", "replace")
        dpop_val = str(raw_dpop).strip()
        if dpop_val:
            break
    if dpop_val:
        out[dpop_field or "dpop_list"] = dpop_val

    for hk, vk in HEADER_MAP_TO_VALUE:
        raw = None
        try:
            raw = flow_headers.get(hk)
        except Exception:
            raw = None
        if raw is None:
            try:
                for k in list(flow_headers.keys()):
                    kn = k.decode("utf-8", "replace") if isinstance(k, bytes) else str(k)
                    if kn.lower() == hk.lower():
                        raw = flow_headers.get(kn)
                        break
            except Exception:
                pass
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        val = str(raw).strip()
        if val:
            out[vk] = val
    return out


def atomic_write_capture_file(payload: Dict[str, Any]) -> None:
    capture_type = str(payload.get("capture_type") or "")
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = capture_json_path(capture_type)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_capture_file(capture_type: str = "") -> Optional[Dict[str, Any]]:
    path = capture_json_path(capture_type)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


def on_sale_list_response_path(seller_id: str) -> str:
    """MITM 写入的「在售列表 items/get_items 响应体」按 seller_id 分文件，避免多账号并发覆盖。"""
    sid = str(int(str(seller_id).strip()))
    return os.path.join(ssl_mitm_data_dir(), f"items_get_items_on_sale_response_{sid}.json")


def clear_on_sale_list_response_file(seller_id: str) -> None:
    p = on_sale_list_response_path(seller_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def atomic_write_on_sale_list_response(seller_id: str, payload: Dict[str, Any]) -> None:
    sid = str(int(str(seller_id).strip()))
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = on_sale_list_response_path(sid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_on_sale_list_response(seller_id: str) -> Optional[Dict[str, Any]]:
    path = on_sale_list_response_path(seller_id)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


def canonical_mercari_item_id(item_id: str) -> str:
    """商品页 / API 常见 ``m123`` 或纯数字，统一为 ``m`` + 数字（可解析时）。"""
    s = str(item_id or "").strip()
    if not s:
        return ""
    low = s.lower()
    if len(low) > 1 and low[0] == "m" and low[1:].isdigit():
        return "m" + low[1:]
    if s.isdigit():
        return "m" + s
    return s


def item_get_response_path(item_id: str) -> str:
    cid = canonical_mercari_item_id(item_id)
    return os.path.join(ssl_mitm_data_dir(), f"items_get_response_{cid}.json")


def clear_item_get_response_file(item_id: str) -> None:
    p = item_get_response_path(item_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def atomic_write_item_get_response(item_id: str, payload: Dict[str, Any]) -> None:
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        return
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = item_get_response_path(cid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_item_get_response(item_id: str) -> Optional[Dict[str, Any]]:
    path = item_get_response_path(item_id)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


def trading_list_response_path(seller_id: str) -> str:
    """出售中订单列表：``items/get_items``（status=trading）响应，按 seller_id 分文件。"""
    sid = str(int(str(seller_id).strip()))
    return os.path.join(ssl_mitm_data_dir(), f"items_get_items_trading_response_{sid}.json")


def clear_trading_list_response_file(seller_id: str) -> None:
    p = trading_list_response_path(seller_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def atomic_write_trading_list_response(seller_id: str, payload: Dict[str, Any]) -> None:
    sid = str(int(str(seller_id).strip()))
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = trading_list_response_path(sid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_trading_list_response(seller_id: str) -> Optional[Dict[str, Any]]:
    path = trading_list_response_path(seller_id)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


def sold_out_list_response_path(seller_id: str) -> str:
    """已售完历史：``items/get_items``（status=sold_out）响应，按 seller_id 分文件。"""
    sid = str(int(str(seller_id).strip()))
    return os.path.join(ssl_mitm_data_dir(), f"items_get_items_sold_out_response_{sid}.json")


def clear_sold_out_list_response_file(seller_id: str) -> None:
    p = sold_out_list_response_path(seller_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def atomic_write_sold_out_list_response(seller_id: str, payload: Dict[str, Any]) -> None:
    sid = str(int(str(seller_id).strip()))
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = sold_out_list_response_path(sid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_sold_out_list_response(seller_id: str) -> Optional[Dict[str, Any]]:
    path = sold_out_list_response_path(seller_id)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


def transaction_evidence_response_path(item_id: str) -> str:
    cid = canonical_mercari_item_id(item_id)
    return os.path.join(ssl_mitm_data_dir(), f"transaction_evidences_get_response_{cid}.json")


def clear_transaction_evidence_response_file(item_id: str) -> None:
    p = transaction_evidence_response_path(item_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def atomic_write_transaction_evidence_response(item_id: str, payload: Dict[str, Any]) -> None:
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        return
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = transaction_evidence_response_path(cid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_transaction_evidence_response(item_id: str) -> Optional[Dict[str, Any]]:
    path = transaction_evidence_response_path(item_id)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


# ============ 代办事项 services/todolist/v1/list ============
# 请求路径不含 seller_id，多账号通过 run_meilu_serial_async 串行隔离；
# 单一 latest 文件即可，同步函数进入时 clear、抓取后 read。

def todolist_response_path() -> str:
    return os.path.join(ssl_mitm_data_dir(), "todolist_latest_response.json")


def clear_todolist_response_file() -> None:
    p = todolist_response_path()
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def atomic_write_todolist_response(payload: Dict[str, Any]) -> None:
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = todolist_response_path()
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def read_todolist_response() -> Optional[Dict[str, Any]]:
    path = todolist_response_path()
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

