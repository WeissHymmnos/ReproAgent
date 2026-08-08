"""长研报 Markdown 分块与因子合并去重。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from reproagent.models.factor_spec import ParsedFactorSpec

# 默认单块字符上限（中文研报约 4–6k tokens 量级）
DEFAULT_CHUNK_CHARS = 10_000
# 块间重叠，避免表格/段落被切断
DEFAULT_OVERLAP_CHARS = 400


def split_markdown_chunks(
    markdown: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    """按页标记或长度切分 Markdown。

    优先按 ``<!-- page: N -->`` / ``<!-- page:N -->`` 分页；
    单页过长再按段落硬切。
    """
    text = markdown or ""
    if not text.strip():
        return []

    if len(text) <= max_chars:
        return [text]

    page_pat = re.compile(r"(?m)^(?:<!--\s*page\s*:\s*\d+\s*-->|#+\s*page\s+\d+)")
    splits = list(page_pat.finditer(text))
    if len(splits) >= 2:
        pages: list[str] = []
        for i, m in enumerate(splits):
            start = m.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            pages.append(text[start:end].strip())
        # 合并过短页，拆分过长页
        return _pack_segments(pages, max_chars=max_chars, overlap=overlap)

    # 无页标记：按双换行段落
    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    return _pack_segments(paras, max_chars=max_chars, overlap=overlap)


def _pack_segments(
    segments: list[str],
    *,
    max_chars: int,
    overlap: int,
) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for seg in segments:
        if not seg:
            continue
        # 单段超长：硬切
        if len(seg) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_hard_split(seg, max_chars=max_chars, overlap=overlap))
            continue
        candidate = f"{buf}\n\n{seg}".strip() if buf else seg
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            # 重叠尾部
            if overlap > 0 and chunks:
                tail = chunks[-1][-overlap:]
                buf = f"{tail}\n\n{seg}".strip()
            else:
                buf = seg
    if buf:
        chunks.append(buf)
    return chunks or ([segments[0][:max_chars]] if segments else [])


def _hard_split(text: str, *, max_chars: int, overlap: int) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(text)
    step = max(1, max_chars - overlap)
    while i < n:
        out.append(text[i : i + max_chars])
        i += step
    return out


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").lower())


def merge_factor_specs(specs: Iterable[ParsedFactorSpec]) -> list[ParsedFactorSpec]:
    """按 factor_name / factor_name_cn 去重合并，保留置信度更高者。"""
    best: dict[str, ParsedFactorSpec] = {}
    order: list[str] = []

    for spec in specs:
        key = _norm_name(spec.factor_name) or _norm_name(spec.factor_name_cn)
        if not key:
            key = spec.id or f"anon-{len(best)}"
        if key not in best:
            best[key] = spec
            order.append(key)
            continue
        prev = best[key]
        # 更高置信度优先；置信度相同取公式更长（信息更多）
        if (spec.extraction_confidence, len(spec.formula or "")) > (
            prev.extraction_confidence,
            len(prev.formula or ""),
        ):
            best[key] = spec

    return [best[k] for k in order]


def needs_chunking(markdown: str, threshold: int = DEFAULT_CHUNK_CHARS) -> bool:
    return len(markdown or "") > threshold
