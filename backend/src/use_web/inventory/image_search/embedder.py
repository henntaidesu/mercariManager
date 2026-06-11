# -*- coding: utf-8 -*-
"""CLIP 图片特征提取器（ONNX Runtime，纯 CPU 友好）。

- 模型：CLIP ViT-B/32 视觉编码器，int8 量化 ONNX（约 88MB），弱 CPU 单图推理几十毫秒级
- 懒加载单例：不使用图片搜索时不加载模型、不占内存
- 模型文件不存在时自动下载到 backend/models/（支持 hf-mirror 镜像兜底）
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

import numpy as np
from PIL import Image

from ....app_paths import backend_root

logger = logging.getLogger(__name__)

# 模型标识：写入 image_embeddings.model_name，换模型时旧向量自动重建
MODEL_NAME = "clip-vit-b32-onnx-q8"
_MODEL_FILENAME = "clip_vit_b32_vision_quantized.onnx"
_MODEL_URLS = [
    "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
    # 国内网络访问 huggingface 失败时的镜像兜底
    "https://hf-mirror.com/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
]

_IMAGE_SIZE = 224
_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

_lock = threading.Lock()
_session = None
_input_name: Optional[str] = None
_output_name: Optional[str] = None
_load_error: Optional[str] = None


def model_dir() -> str:
    return os.path.join(str(backend_root()), "models")


def _model_path() -> str:
    return os.path.join(model_dir(), _MODEL_FILENAME)


def _download_model(dest: str) -> None:
    """流式下载模型文件（先写 .part 再改名，避免半截文件被误用）。"""
    import requests

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urls: List[str] = []
    override = (os.environ.get("IMAGE_SEARCH_MODEL_URL") or "").strip()
    if override:
        urls.append(override)
    urls.extend(_MODEL_URLS)

    last_err: Optional[Exception] = None
    for url in urls:
        tmp = dest + ".part"
        try:
            logger.info("[image_search] 正在下载 CLIP 模型: %s", url)
            with requests.get(url, stream=True, timeout=(15, 600)) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            os.replace(tmp, dest)
            logger.info("[image_search] CLIP 模型下载完成: %s", dest)
            return
        except Exception as exc:
            last_err = exc
            logger.warning("[image_search] 模型下载失败 (%s): %s", url, exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    raise RuntimeError(f"CLIP 模型下载失败，请检查网络或手动放置模型文件到 {dest}：{last_err}")


def _pick_output_name(session) -> str:
    """优先取投影后的 image_embeds（512 维）；不同导出版本输出名可能不同。"""
    names = [o.name for o in session.get_outputs()]
    for preferred in ("image_embeds", "pooler_output"):
        if preferred in names:
            return preferred
    return names[0]


def _ensure_session():
    global _session, _input_name, _output_name, _load_error
    if _session is not None:
        return _session
    with _lock:
        if _session is not None:
            return _session
        try:
            import onnxruntime as ort
        except ImportError as exc:
            _load_error = "缺少 onnxruntime 依赖，请先 pip install -r requirements.txt"
            raise RuntimeError(_load_error) from exc

        path = _model_path()
        if not os.path.exists(path):
            try:
                _download_model(path)
            except Exception as exc:
                _load_error = str(exc)
                raise RuntimeError(_load_error) from exc

        try:
            opts = ort.SessionOptions()
            # 弱机器友好：限制推理线程数，避免与业务争抢 CPU
            threads = int(os.environ.get("IMAGE_SEARCH_THREADS", "2") or 2)
            opts.intra_op_num_threads = max(1, threads)
            opts.inter_op_num_threads = 1
            sess = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        except Exception as exc:
            _load_error = f"CLIP 模型加载失败: {exc}"
            raise RuntimeError(_load_error) from exc

        _input_name = sess.get_inputs()[0].name
        _output_name = _pick_output_name(sess)
        _session = sess
        _load_error = None
        logger.info("[image_search] CLIP 模型已加载（输出: %s）", _output_name)
        return _session


def get_load_error() -> Optional[str]:
    return _load_error


def is_loaded() -> bool:
    return _session is not None


def _preprocess(img: Image.Image) -> np.ndarray:
    """CLIP 标准预处理：短边缩放 224 → 中心裁剪 → 归一化 → CHW。"""
    img = img.convert("RGB")
    w, h = img.size
    scale = _IMAGE_SIZE / min(w, h)
    img = img.resize((max(_IMAGE_SIZE, round(w * scale)), max(_IMAGE_SIZE, round(h * scale))), Image.Resampling.BICUBIC)
    w, h = img.size
    left = (w - _IMAGE_SIZE) // 2
    top = (h - _IMAGE_SIZE) // 2
    img = img.crop((left, top, left + _IMAGE_SIZE, top + _IMAGE_SIZE))
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - _CLIP_MEAN) / _CLIP_STD
    return arr.transpose(2, 0, 1)[np.newaxis, :]  # [1, 3, 224, 224]


def embed_image(img: Image.Image) -> np.ndarray:
    """提取单张图片特征，返回 L2 归一化后的 float32 向量。

    模型不可用时抛 RuntimeError（含可展示给用户的中文信息）。
    """
    sess = _ensure_session()
    out = sess.run([_output_name], {_input_name: _preprocess(img)})[0]
    vec = np.asarray(out, dtype=np.float32)
    if vec.ndim == 3:
        vec = vec[:, 0, :]  # 取 CLS token
    vec = vec.reshape(-1)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)
