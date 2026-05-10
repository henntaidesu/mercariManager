# -*- coding: utf-8 -*-
"""mitmproxy 插件：拦截关键接口并写入 items_get_items_capture.json"""

from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mitmproxy import ctx  # noqa: E402
from mitmproxy import http  # noqa: E402

from src.ssl_mitm_proxy.capture_config import (  # noqa: E402
    atomic_write_capture_file,
    atomic_write_item_get_response,
    atomic_write_on_sale_list_response,
    canonical_mercari_item_id,
    headers_to_value_dict,
    parse_capture_target,
)


def _log_line(msg: str) -> None:
    try:
        ctx.log.info(msg)
        print(msg, file=sys.stderr, flush=True)
    except Exception:
        pass


class MitmTrafficLog:
    """类似 Charles：每个经过代理的 HTTP(S) 请求打印一行 METHOD + URL。"""

    def request(self, flow: http.HTTPFlow) -> None:
        try:
            req = flow.request
            method = (req.method or "?").strip().upper() or "?"
            url = (req.pretty_url or "").strip() or "(no url)"
            _log_line(f"[MITM] {method} {url}")
        except Exception:
            pass


class MercariCapture:
    def request(self, flow: http.HTTPFlow) -> None:
        try:
            req = flow.request
            method = (req.method or "").strip().upper()
            host = req.host or ""
            path = req.path or ""
            url = req.pretty_url or ""
            try:
                qraw = req.query
                if isinstance(qraw, bytes):
                    qstr = qraw.decode("utf-8", "replace")
                else:
                    qstr = str(qraw or "")
            except Exception:
                qstr = ""
            meta = parse_capture_target(url, path, host, qstr, method=method)
            if not meta:
                return
            value_headers = headers_to_value_dict(req.headers, dpop_field=str(meta.get("dpop_field") or "dpop_list"))
            if not value_headers:
                return
            payload = {
                "ts": int(time.time() * 1000),
                "capture_type": meta.get("capture_type") or "",
                "seller_id": meta.get("seller_id") or "",
                "item_id": meta.get("item_id") or "",
                "status_values": meta.get("status_values") or [],
                "http_method": meta.get("http_method") or method,
                "dpop_field": meta.get("dpop_field") or "dpop_list",
                "url": meta.get("full_url") or url,
                "value_patch": value_headers,
            }
            atomic_write_capture_file(payload)
            try:
                keys = sorted(value_headers.keys())
                ctype = payload.get("capture_type") or "unknown"
                msg = (
                    f"[MITM] {ctype} 已写入 capture seller_id={payload.get('seller_id') or '-'} "
                    f"dpop_field={payload.get('dpop_field') or '-'} "
                    f"头字段({len(keys)}): {', '.join(keys)}"
                )
                _log_line(msg)
            except Exception:
                pass
        except Exception:
            pass

    def response(self, flow: http.HTTPFlow) -> None:
        """在售列表 items/get_items、单件详情 items/get 的 JSON 响应体落盘。"""
        try:
            req = flow.request
            resp = flow.response
            if resp is None:
                return
            method = (req.method or "").strip().upper()
            host = req.host or ""
            path = req.path or ""
            url = req.pretty_url or ""
            try:
                qraw = req.query
                if isinstance(qraw, bytes):
                    qstr = qraw.decode("utf-8", "replace")
                else:
                    qstr = str(qraw or "")
            except Exception:
                qstr = ""
            meta = parse_capture_target(url, path, host, qstr, method=method)
            if not meta:
                return
            code = int(resp.status_code or 0)
            if code != 200:
                return
            body_text = resp.get_text(strict=False)
            if not (body_text or "").strip():
                return
            body_json = json.loads(body_text)
            ctype = str(meta.get("capture_type") or "")
            dpop = str(meta.get("dpop_field") or "")

            if ctype == "items_get_items" and dpop == "dpop_on_sale_list":
                sid = str(meta.get("seller_id") or "").strip()
                if not sid.isdigit():
                    return
                atomic_write_on_sale_list_response(
                    sid,
                    {
                        "ts": int(time.time() * 1000),
                        "seller_id": sid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] items/get_items 在售列表响应已写入 seller_id={sid} "
                    f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                )
                return

            if ctype == "items_get" and dpop == "dpop_item_get_info":
                iid = canonical_mercari_item_id(str(meta.get("item_id") or ""))
                if not iid:
                    return
                atomic_write_item_get_response(
                    iid,
                    {
                        "ts": int(time.time() * 1000),
                        "item_id": iid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] items/get 商品详情响应已写入 item_id={iid} "
                    f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                )
        except Exception:
            pass


addons = [MitmTrafficLog(), MercariCapture()]
