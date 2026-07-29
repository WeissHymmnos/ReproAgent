"""Detect and strip page headers/footers from research PDF parses.

Strategies (combined):
1. Geometry — blocks in top/bottom page bands
2. Pattern — broker disclaimers, page numbers, department labels
3. Cross-page frequency — short lines that repeat on many pages

Does *not* remove body content that happens to mention the same words
unless geometry or frequency also supports removal.
"""

from __future__ import annotations

import re
from collections import Counter

from finreportparser.types import BlockType, PageBlock, PageResult

# Top / bottom margins as fraction of page height
_TOP_BAND = 0.08
_BOTTOM_BAND = 0.10

# Patterns that are almost always headers/footers in Chinese sell-side PDFs
_HEADER_FOOTER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"^固收研究\s*$",
        r"^固定收益研究\s*$",
        r"^金融工程研究\s*$",
        r"^证券研究报告\s*$",
        r"^深度研究\s*$",
        r"^华泰证券\s*$",
        r"^HUATAI\s*SECURITIES\s*$",
        r"^HAITONG\s*$",
        r"^海通证券\s*$",
        r"^中信证券\s*$",
        r"^中金公司\s*$",
        r"^国泰君安\s*$",
        r"^招商证券\s*$",
        r"^免责声明和披露以及分析师声明是报告的一部分[，,].*请务必一起阅读[。.]?\s*\d*\s*$",
        r"^请务必阅读正文之后的信息披露和法律声明\s*$",
        r"^请仔细阅读本报告末页声明\s*$",
        r"^本报告仅供.*参考\s*$",
        r"^[-—–\s]*\d{1,3}[-—–\s]*$",  # bare page number
        r"^第\s*\d+\s*页\s*(共\s*\d+\s*页)?\s*$",
        r"^\d+\s*/\s*\d+\s*$",
    )
)

# Substring markers for short lines (len-bounded) — not applied to long body paras
_SHORT_MARKERS: tuple[str, ...] = (
    "免责声明和披露以及分析师声明是报告的一部分",
    "请务必一起阅读",
    "请务必阅读正文之后",
    "HUATAI SECURITIES",
    "HUATAI SECURITES",  # OCR typo
)


def _norm_key(text: str) -> str:
    t = re.sub(r"\s+", "", text or "")
    # strip trailing page numbers for frequency matching
    t = re.sub(r"\d+$", "", t)
    return t


def is_header_footer_text(text: str | None, *, allow_long: bool = False) -> bool:
    """Pattern-based check for a single line/block of text."""
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False

    for pat in _HEADER_FOOTER_PATTERNS:
        if pat.search(stripped):
            return True

    # Short-line markers only (avoid killing long paragraphs that quote disclaimers)
    if len(stripped) <= 80 or allow_long:
        for m in _SHORT_MARKERS:
            if m in stripped and len(stripped) < 120:
                return True

    # Very short all-caps brand lines
    if len(stripped) <= 24 and re.fullmatch(r"[A-Z][A-Z\s\.]+", stripped):
        return True

    return False


def is_header_footer_block(
    block: PageBlock,
    *,
    page_height: float | None = None,
    repeated_keys: set[str] | None = None,
) -> bool:
    """True if block should be dropped as header/footer."""
    if block.type in (BlockType.HEADER, BlockType.FOOTER):
        return True

    # Never drop tables / formulas by geometry alone
    if block.type in (BlockType.TABLE, BlockType.FORMULA, BlockType.MERMAID):
        # still drop if text is pure disclaimer (rare)
        if block.type == BlockType.TABLE:
            return False
        return is_header_footer_text(block.text)

    text = (block.text or "").strip()
    if not text:
        return False

    # Chart blocks that are only broker logos
    if block.type == BlockType.CHART:
        title = ""
        if block.metadata and isinstance(block.metadata.get("chart_meta"), dict):
            title = str(block.metadata["chart_meta"].get("title") or "")
        blob = f"{title}\n{text}"
        if is_header_footer_text(title) or is_header_footer_text(
            text.split("\n")[0] if text else "", allow_long=False
        ):
            # logo-only: short description + brand keywords
            if len(text) < 200 and any(
                k in blob for k in ("华泰证券", "HUATAI", "HAITONG", "海通证券")
            ):
                return True
        return False

    if is_header_footer_text(text):
        return True

    # Geometry: top/bottom band + short text
    if page_height and page_height > 0 and block.bbox is not None:
        y0, y1 = block.bbox.y0, block.bbox.y1
        h = y1 - y0
        in_top = y1 <= page_height * _TOP_BAND or y0 <= page_height * (_TOP_BAND * 0.6)
        in_bottom = y0 >= page_height * (1.0 - _BOTTOM_BAND)
        short = len(text) <= 60 and "\n" not in text
        # slightly longer footer disclaimers sit in bottom band
        footerish = len(text) <= 100 and (
            "免责" in text or "请务必" in text or re.search(r"\d{1,3}$", text)
        )
        if in_top and short:
            return True
        if in_bottom and (short or footerish):
            return True
        # Tiny height strip at edges
        if h > 0 and h < page_height * 0.04 and (in_top or in_bottom) and len(text) < 40:
            return True

    # Cross-page frequency
    if repeated_keys is not None:
        key = _norm_key(text)
        if key and key in repeated_keys and len(text) <= 80:
            return True

    return False


def collect_repeated_line_keys(
    pages: list[PageResult],
    *,
    min_pages: int | None = None,
    max_len: int = 80,
) -> set[str]:
    """Keys of short text lines appearing on enough pages to be header/footer."""
    if not pages:
        return set()
    n_pages = len(pages)
    threshold = min_pages if min_pages is not None else max(2, min(3, n_pages // 4 or 2))
    # per-page unique keys
    page_keys: list[set[str]] = []
    for page in pages:
        keys: set[str] = set()
        for b in page.blocks:
            if b.type not in (BlockType.TEXT, BlockType.HEADER, BlockType.FOOTER):
                continue
            t = (b.text or "").strip()
            if not t or len(t) > max_len:
                continue
            keys.add(_norm_key(t))
        page_keys.append(keys)

    counter: Counter[str] = Counter()
    for keys in page_keys:
        counter.update(keys)

    return {k for k, c in counter.items() if k and c >= threshold}


def filter_page_headers_footers(
    page: PageResult,
    *,
    repeated_keys: set[str] | None = None,
) -> PageResult:
    """Return a copy of page with header/footer blocks removed."""
    kept: list[PageBlock] = []
    for b in page.blocks:
        if is_header_footer_block(
            b, page_height=page.height, repeated_keys=repeated_keys
        ):
            continue
        kept.append(b)
    return page.model_copy(update={"blocks": kept})


def filter_document_headers_footers(pages: list[PageResult]) -> list[PageResult]:
    """Two-pass filter: frequency across document + per-page geometry/patterns."""
    repeated = collect_repeated_line_keys(pages)
    return [filter_page_headers_footers(p, repeated_keys=repeated) for p in pages]


def strip_header_footer_lines(text: str) -> str:
    """Line-level cleanup for residual header/footer strings in free text."""
    if not text:
        return text
    out: list[str] = []
    for line in text.split("\n"):
        if is_header_footer_text(line.strip()):
            continue
        out.append(line)
    # collapse excessive blank lines
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
