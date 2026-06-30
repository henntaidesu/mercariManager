# -*- coding: utf-8 -*-
"""出品图片水印：在右下角叠加「出品账号名 + 出品日期」。

每次出品时按需生成（不修改原图），生成的带水印图片写入临时文件后上传。
任一张处理失败时回退为原图，绝不中断出品流程。
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from typing import List, Optional, Sequence

log = logging.getLogger(__name__)

# Windows 常见可显示中/日文的字体（按优先级），取第一个存在的。
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/meiryo.ttc",   # メイリオ（日）
    "C:/Windows/Fonts/YuGothM.ttc",  # 游ゴシック（日）
    "C:/Windows/Fonts/msgothic.ttc", # MS ゴシック（日）
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑（中）
    "C:/Windows/Fonts/simhei.ttf",   # 黑体（中）
    "C:/Windows/Fonts/arial.ttf",
)


def _account_name(account_id: Optional[int]) -> Optional[str]:
    """取煤炉账号名；取不到返回 None。"""
    if account_id is None:
        return None
    try:
        from src.db_manage.models.mercari_account import MercariAccountModel

        acc = MercariAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        name = str(getattr(acc, "account_name", "") or "").strip()
        return name or None
    except Exception:
        return None


def build_watermark_text(account_id: Optional[int]) -> str:
    """水印文案：「账号名  MM月DD日」；无账号名时仅日期。"""
    date_str = datetime.now().strftime("%m月%d日")
    name = _account_name(account_id)
    return f"{name}  {date_str}" if name else date_str


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            if os.path.isfile(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def apply_watermark_to_images(local_paths: Sequence[str], text: str) -> List[str]:
    """对每张本地图片右下角叠加水印，返回新生成的临时图片路径列表。

    单张失败时回退为原图路径。
    """
    text = (text or "").strip()
    if not text:
        return list(local_paths)

    from PIL import Image, ImageDraw

    out: List[str] = []
    for src in local_paths:
        try:
            out.append(_watermark_one(src, text, Image, ImageDraw))
        except Exception as exc:
            log.warning("水印生成失败，使用原图: %s (%s)", src, exc)
            out.append(src)
    return out


def _watermark_one(src: str, text: str, Image, ImageDraw) -> str:
    with Image.open(src) as im:
        im = im.convert("RGBA")
        w, h = im.size

        # 字号随图片宽度自适应（约 1/28），并设下限
        font_size = max(16, int(w / 28))
        font = _load_font(font_size)

        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 文字尺寸（兼容新旧 Pillow）
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
        except Exception:
            tw, th = draw.textsize(text, font=font)
            bbox = (0, 0, tw, th)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        margin = max(8, int(w / 60))
        pad = max(4, int(font_size / 3))
        x = w - tw - margin
        y = h - th - margin

        # 半透明黑底，提升可读性
        draw.rectangle(
            [x - pad, y - pad, x + tw + pad, y + th + pad],
            fill=(0, 0, 0, 120),
        )
        # 文字左上偏移 bbox 原点，使字形对齐到 (x, y)
        draw.text((x - bbox[0], y - bbox[1]), text, font=font, fill=(255, 255, 255, 235))

        merged = Image.alpha_composite(im, overlay).convert("RGB")

        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tf.close()
        merged.save(tf.name, format="JPEG", quality=92)
        return tf.name
