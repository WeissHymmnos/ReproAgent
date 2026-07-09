"""缓存 key 计算。"""

from __future__ import annotations

import hashlib


def compute_cache_key(
    pdf_hash: str,
    parser_version: str,
    extraction_model_id: str,
) -> str:
    """缓存 key = sha256(pdf_hash|parser_version|model) 截断 16 位。

    parser/model 版本变化 → key 变化 → 缓存失效。
    """
    raw = f"{pdf_hash}|{parser_version}|{extraction_model_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
