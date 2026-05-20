# -*- coding: utf-8 -*-
"""
管理番号 5 进制暗号：字符集 ``-=~<>`` 对应 0–4（低位在前编码）。

出品时写在商品说明最末行，无「管理番号：」前缀；解析端与明文格式向下兼容。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

MGMT_CIPHER_ALPHABET = "-=~<>"
_CIPHER_CHAR_SET = set(MGMT_CIPHER_ALPHABET)
_CIPHER_TOKEN_RE = re.compile(
    r"^([-=~<>]+)(?:\s*[*xX×]\s*(\d+))?$",
    re.UNICODE,
)


def encode_mgmt_id(value: int) -> str:
    """将正整数 inventory.id 编码为暗号串。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("invalid management id") from None
    if n < 0:
        raise ValueError("invalid management id")
    if n == 0:
        return MGMT_CIPHER_ALPHABET[0]
    chars: List[str] = []
    while n > 0:
        chars.append(MGMT_CIPHER_ALPHABET[n % 5])
        n //= 5
    return "".join(chars)


def decode_mgmt_id_cipher(token: str) -> Optional[int]:
    """解码单个暗号 token；非法则返回 None。"""
    s = (token or "").strip()
    if not s or not all(c in _CIPHER_CHAR_SET for c in s):
        return None
    n = 0
    mult = 1
    for c in s:
        n += MGMT_CIPHER_ALPHABET.index(c) * mult
        mult *= 5
    return n if n > 0 else None


def encode_mgmt_ids(ids: List[int], sep: str = "、") -> str:
    parts: List[str] = []
    for raw in ids:
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            parts.append(encode_mgmt_id(n))
    return sep.join(parts)


def _split_cipher_chunks(segment: str) -> List[str]:
    parts: List[str] = []
    for part in re.split(r"[,，、\s]+", segment or ""):
        p = (part or "").strip()
        if p:
            parts.append(p)
    return parts


def _cipher_token_base_and_qty(token: str) -> Tuple[str, int]:
    t = (token or "").strip()
    if not t:
        return "", 1
    m = _CIPHER_TOKEN_RE.match(t)
    if not m:
        return "", 1
    base = (m.group(1) or "").strip()
    qraw = (m.group(2) or "").strip()
    if not qraw:
        return base, 1
    try:
        q = int(qraw)
    except (TypeError, ValueError):
        q = 1
    return base, max(1, q)


def is_cipher_mgmt_line(line: str) -> bool:
    """整行是否仅由暗号 token（及分隔符）组成。"""
    s = (line or "").strip()
    if not s:
        return False
    if re.search(r"管理\s*(?:ID|番号)\s*[:：]", s, re.IGNORECASE):
        return False
    if re.search(r"バーコード\s*[:：]", s, re.IGNORECASE):
        return False
    has_token = False
    for part in _split_cipher_chunks(s):
        base, _qty = _cipher_token_base_and_qty(part)
        if not base or not all(c in _CIPHER_CHAR_SET for c in base):
            return False
        has_token = True
    return has_token


def parse_trailing_cipher_mgmt_tokens(text: Optional[str]) -> List[Tuple[int, int]]:
    """
    从说明**最末非空行**解析暗号管理番号。
    返回 [(inventory_id, quantity), ...]
    """
    if text is None:
        return []
    s = str(text).strip()
    if not s:
        return []

    lines = s.splitlines()
    last_line = ""
    for raw in reversed(lines):
        t = str(raw or "").strip()
        if t:
            last_line = t
            break
    if not last_line or not is_cipher_mgmt_line(last_line):
        return []

    out: List[Tuple[int, int]] = []
    for part in _split_cipher_chunks(last_line):
        base, qty = _cipher_token_base_and_qty(part)
        if not base:
            continue
        mid = decode_mgmt_id_cipher(base)
        if mid is None:
            continue
        out.append((mid, qty))
    return out
