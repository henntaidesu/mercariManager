# -*- coding: utf-8 -*-
"""
库存商品图片特征向量表（图片搜索索引）

每行对应一张商品图的 CLIP 特征向量；vector 为 float32 数组的原始字节（BLOB）。
model_name 记录生成向量的模型标识，换模型后旧向量自动视为缺失并重建。
"""

from typing import Dict, Any, List
from ..base_model import BaseModel


class ImageEmbeddingModel(BaseModel):
    """图片特征向量表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "image_embeddings"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'inventory_id': {
                'type': 'INTEGER',
                'not_null': True,
            },
            # 商品图路径，如 /imges/xxx.jpg（与 inventory.images_json 中的值一致）
            'image_path': {
                'type': 'TEXT',
                'not_null': True,
            },
            'model_name': {
                'type': 'TEXT',
                'not_null': True,
            },
            # float32 向量原始字节，维度 = len(vector) / 4
            'vector': {
                'type': 'BLOB',
                'not_null': True,
            },
            'updated_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_image_embeddings_inventory', 'columns': ['inventory_id']},
            {
                'name': 'idx_image_embeddings_path_model',
                'columns': ['image_path', 'model_name'],
                'unique': True,
            },
        ]
