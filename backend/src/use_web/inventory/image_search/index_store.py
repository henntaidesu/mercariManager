# -*- coding: utf-8 -*-
"""特征向量持久化（image_embeddings 表）与内存检索矩阵。

库存量级（几百~几千张图）下 numpy 暴力余弦检索毫秒级完成，无需向量库；
向量落 SQLite BLOB，启动/变更后加载为一个 float32 矩阵常驻内存。
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from ....db_manage.database import DatabaseManager
from .embedder import MODEL_NAME

db = DatabaseManager()

_lock = threading.Lock()
# 缓存：(矩阵 [N,D], [(inventory_id, image_path), ...])；None 表示需要重新加载
_cached_matrix: Optional[np.ndarray] = None
_cached_rows: List[Tuple[int, str]] = []
_cache_valid = False


def invalidate_cache() -> None:
    global _cache_valid
    with _lock:
        _cache_valid = False


def get_matrix() -> Tuple[Optional[np.ndarray], List[Tuple[int, str]]]:
    """返回 (向量矩阵, 对应的 (inventory_id, image_path) 列表)；索引为空时矩阵为 None。"""
    global _cached_matrix, _cached_rows, _cache_valid
    with _lock:
        if _cache_valid:
            return _cached_matrix, _cached_rows
        rows = db.execute_query(
            "SELECT inventory_id, image_path, vector FROM [image_embeddings] WHERE model_name = ?",
            (MODEL_NAME,),
        )
        metas: List[Tuple[int, str]] = []
        vectors: List[np.ndarray] = []
        dim = None
        for inv_id, path, blob in rows or []:
            if not blob:
                continue
            vec = np.frombuffer(blob, dtype=np.float32)
            if dim is None:
                dim = vec.shape[0]
            if vec.shape[0] != dim:
                continue  # 维度不一致的脏数据，跳过（重建索引时会覆盖）
            metas.append((int(inv_id), str(path)))
            vectors.append(vec)
        _cached_matrix = np.stack(vectors) if vectors else None
        _cached_rows = metas
        _cache_valid = True
        return _cached_matrix, _cached_rows


def indexed_count() -> int:
    rows = db.execute_query(
        "SELECT COUNT(*) FROM [image_embeddings] WHERE model_name = ?", (MODEL_NAME,)
    )
    return int(rows[0][0]) if rows else 0


def list_indexed_paths() -> Dict[str, int]:
    """当前模型下已索引的 {image_path: inventory_id}。"""
    rows = db.execute_query(
        "SELECT image_path, inventory_id FROM [image_embeddings] WHERE model_name = ?",
        (MODEL_NAME,),
    )
    return {str(p): int(i) for p, i in rows or []}


def upsert_vector(inventory_id: int, image_path: str, vec: np.ndarray) -> None:
    db.execute_update(
        """
        INSERT INTO [image_embeddings] (inventory_id, image_path, model_name, vector, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(image_path, model_name) DO UPDATE SET
            inventory_id = excluded.inventory_id,
            vector = excluded.vector,
            updated_at = CURRENT_TIMESTAMP
        """,
        (int(inventory_id), image_path, MODEL_NAME, np.asarray(vec, dtype=np.float32).tobytes()),
    )
    invalidate_cache()


def delete_paths(paths: List[str]) -> None:
    if not paths:
        return
    for i in range(0, len(paths), 200):
        chunk = paths[i : i + 200]
        qs = ", ".join("?" for _ in chunk)
        db.execute_update(
            f"DELETE FROM [image_embeddings] WHERE model_name = ? AND image_path IN ({qs})",
            (MODEL_NAME, *chunk),
        )
    invalidate_cache()


def delete_other_models() -> None:
    """清理旧模型遗留的向量（换模型后一次性回收空间）。"""
    db.execute_update("DELETE FROM [image_embeddings] WHERE model_name != ?", (MODEL_NAME,))
