"""缓存 key 计算。"""

from __future__ import annotations

import hashlib


def compute_cache_key(
    pdf_hash: str,
    parser_version: str,
    extraction_model_id: str,
    data_version: str | None = None,
    settings_hash: str | None = None,
) -> str:
    """缓存 key = sha256(pdf_hash|parser_version|model|data|settings) 截断 16 位。

    parser/model/data/settings 任一变化 → key 变化 → 缓存失效。
    """
    parts = [pdf_hash, parser_version, extraction_model_id]
    if data_version:
        parts.append(data_version)
    if settings_hash:
        parts.append(settings_hash)
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compute_data_version(data_path: str) -> str:
    """从数据文件的 sha256 计算数据版本。

    用法: data_version = compute_data_version(str(local_data_path / 'prices.parquet'))
    """
    from pathlib import Path

    path = Path(data_path)
    if not path.exists():
        return "unknown"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
