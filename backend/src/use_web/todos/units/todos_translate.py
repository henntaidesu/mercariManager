# -*- coding: utf-8 -*-
"""按需翻译端点：把单条（旧）消息日译中并写回 text_zh。

仅 DB + 一次谷歌免费端点请求，无浏览器/串行队列。翻译失败静默回落（返回
``ok=False, text_zh=None``，前端保持原文、不报错）。
"""
from typing import Any, Dict

from fastapi import HTTPException

from ....use_mercari.get_to_du_list.transaction_detail import (
    set_message_translation,
    translate_text,
)
from .todos_models import TranslateMessageRequest


def translate_message_endpoint(req: TranslateMessageRequest) -> Dict[str, Any]:
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")
    zh = translate_text(text)
    if not zh:
        # 静默回落：翻译不可用/失败 → 前端保持原文
        return {"ok": False, "text_zh": None}
    if (req.order_no or "").strip():
        # 持久化失败不影响本次返回（下次仍可重新翻译）
        set_message_translation(req.order_no, req.msg_id, text, zh)
    return {"ok": True, "text_zh": zh}
