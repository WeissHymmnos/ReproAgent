"""Reading-order reconstruction for page blocks.

Merges text/OCR/table/image placeholders by y/x reading order.
Sorting key: (round(y0/10)*10, x0) for multi-column basic support.

Dual-stream reconciliation: when a TABLE block passes the quality gate,
text blocks whose content overlaps >50% with the table's plain text are
suppressed to avoid duplicating table data in the markdown output.
When all tables are rejected, text blocks remain untouched (fail closed
on tables, not text).
"""

import logging
import re
from collections.abc import Callable

from finreportparser.fusion.formula_detect import find_formula_lines
from finreportparser.fusion.formula_map import (
    is_trivial_formula_latex,
    is_usable_latex,
    normalize_formula_text,
    to_latex_approx,
    worth_l3_recognition,
)
from finreportparser.ocr.formula_backend import FormulaRecognizer
from finreportparser.types import BBox, BlockType, FormulaMeta, PageBlock, PageResult

logger = logging.getLogger(__name__)


def _table_plain_text(gfm: str) -> str:
    """Extract plain text from a GFM table string (strip pipes, separators)."""
    lines = gfm.strip().split("\n")
    cells: list[str] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [c.strip() for c in line.split("|")[1:-1]]
        if all(re.match(r"^[-:]+$", p) or p == "" for p in parts):
            continue
        cells.extend(parts)
    return " ".join(cells)


def _content_overlap_ratio(text: str, table_text: str) -> float:
    """Return fraction of *text*'s non-whitespace characters found in *table_text*.

    Uses character-level matching (suitable for Chinese text where word
    tokenisation is non-trivial).  Returns 0.0 if *text* is empty.
    """
    text_chars = re.sub(r"\s+", "", text)
    if not text_chars:
        return 0.0
    table_chars = re.sub(r"\s+", "", table_text)
    if not table_chars:
        return 0.0
    table_set = set(table_chars)
    matched = sum(1 for ch in text_chars if ch in table_set)
    return matched / len(text_chars)


def reconcile_text_with_tables(
    text_blocks: list[PageBlock],
    table_blocks: list[PageBlock],
    *,
    overlap_threshold: float = 0.5,
) -> list[PageBlock]:
    """Suppress text blocks that duplicate accepted table content.

    For each text block, if >*overlap_threshold* of its characters appear
    in any accepted table's plain text, the block is suppressed.

    When *table_blocks* is empty (all tables rejected), all text blocks
    are returned unchanged — fail closed on tables, not text.
    """
    if not table_blocks:
        return list(text_blocks)

    table_texts = [
        _table_plain_text(tbl.text) for tbl in table_blocks
        if tbl.type == BlockType.TABLE and tbl.text
    ]

    if not table_texts:
        return list(text_blocks)

    result: list[PageBlock] = []
    for block in text_blocks:
        if block.type != BlockType.TEXT or not block.text:
            result.append(block)
            continue
        max_overlap = 0.0
        for tt in table_texts:
            ratio = _content_overlap_ratio(block.text, tt)
            if ratio > max_overlap:
                max_overlap = ratio
        if max_overlap > overlap_threshold:
            continue
        result.append(block)
    return result


def sort_blocks_reading_order(blocks: list[PageBlock]) -> list[PageBlock]:
    """Sort blocks by (rounded_y_band, x0) reading order.

    Blocks without a bbox are placed at the end, preserving their
    relative order (stable sort).
    """
    with_bbox = [b for b in blocks if b.bbox is not None]
    without_bbox = [b for b in blocks if b.bbox is None]

    with_bbox.sort(
        key=lambda b: (round(b.bbox.y0 / 10) * 10, b.bbox.x0)
    )

    return with_bbox + without_bbox


def merge_page_content(
    text_blocks: list[PageBlock],
    ocr_blocks: list[PageBlock] | None = None,
    table_blocks: list[PageBlock] | None = None,
    image_placeholders: list[PageBlock] | None = None,
    needs_ocr: bool = False,
) -> list[PageBlock]:
    """Merge text/OCR/table/image blocks into a single reading-order list.

    Policy:
    - If ocr_blocks non-empty and (no text_blocks OR needs_ocr):
      use ocr_blocks + tables + images, sorted.
    - Else: text_blocks + tables + images, sorted by bbox.
    """
    ocr_blocks = ocr_blocks or []
    table_blocks = table_blocks or []
    image_placeholders = image_placeholders or []

    if ocr_blocks and (not text_blocks or needs_ocr):
        merged = list(ocr_blocks) + list(table_blocks) + list(image_placeholders)
    else:
        reconciled_text = reconcile_text_with_tables(list(text_blocks), list(table_blocks))
        merged = reconciled_text + list(table_blocks) + list(image_placeholders)

    return sort_blocks_reading_order(merged)


def promote_formulas(
    blocks: list[PageBlock],
    recognizer: FormulaRecognizer | None = None,
    crop_callback: Callable[[BBox], bytes] | None = None
) -> list[PageBlock]:
    """Promote formula lines within TEXT blocks to FORMULA blocks."""
    new_blocks = []
    for block in blocks:
        if block.type != BlockType.TEXT or not block.text:
            new_blocks.append(block)
            continue

        spans = find_formula_lines(block.text)
        if not spans:
            # No formulas, just normalize bullet points
            block.text = normalize_formula_text(block.text)
            new_blocks.append(block)
            continue

        lines = block.text.split('\n')
        last_idx = 0

        for span in spans:
            # Add preceding text
            if span.start_idx > last_idx:
                text_part = '\n'.join(lines[last_idx:span.start_idx])
                if text_part.strip():
                    new_blocks.append(PageBlock(
                        type=BlockType.TEXT,
                        bbox=block.bbox,
                        text=normalize_formula_text(text_part),
                        confidence=block.confidence
                    ))

            # Add formula block
            formula_text = '\n'.join(span.lines)
            latex = to_latex_approx(formula_text)

            if is_trivial_formula_latex(latex):
                new_blocks.append(PageBlock(
                    type=BlockType.TEXT,
                    bbox=block.bbox,
                    text=normalize_formula_text(formula_text),
                    confidence=block.confidence
                ))
                last_idx = span.end_idx + 1
                continue

            # Extract eq_number if present
            eq_number = None
            m = re.search(r'\(\s*(\d+)\s*\)\s*$', formula_text)
            if m:
                eq_number = m.group(1)

            source = "l1"
            if recognizer and crop_callback and block.bbox and worth_l3_recognition(formula_text, eq_number):
                try:
                    crop_bbox = block.bbox
                    n_lines = len(lines)
                    if n_lines > 1:
                        h = block.bbox.y1 - block.bbox.y0
                        y0_prime = block.bbox.y0 + (span.start_idx / n_lines) * h
                        y1_prime = block.bbox.y0 + ((span.end_idx + 1) / n_lines) * h
                        pad = 2.0
                        crop_bbox = BBox(
                            x0=block.bbox.x0,
                            y0=max(block.bbox.y0, y0_prime - pad),
                            x1=block.bbox.x1,
                            y1=min(block.bbox.y1, y1_prime + pad)
                        )
                    img_bytes = crop_callback(crop_bbox)
                    meta = recognizer.recognize(img_bytes)
                    if meta:
                        if is_usable_latex(meta.latex):
                            l3_latex = meta.latex
                            l1_usable = is_usable_latex(latex)

                            use_l3 = True
                            if l1_usable:
                                l3_arrays = l3_latex.count("\\begin{array}")
                                l1_arrays = latex.count("\\begin{array}")
                                if l3_arrays > l1_arrays:
                                    use_l3 = False
                                    logger.info(f"Preferring L1 over noisy L3 formula: {l3_latex}")

                            if use_l3:
                                latex = l3_latex
                                source = meta.source
                        else:
                            logger.info(f"Rejected noisy L3 formula: {meta.latex}")
                except Exception as e:
                    logger.warning(f"L3 formula recognition failed: {e}")

            new_blocks.append(PageBlock(
                type=BlockType.FORMULA,
                bbox=block.bbox,
                text=latex,
                confidence=block.confidence,
                metadata={"formula_meta": FormulaMeta(
                    latex=latex,
                    source=source,
                    display=True,
                    eq_number=eq_number
                ).model_dump()}
            ))

            last_idx = span.end_idx + 1

        # Add remaining text
        if last_idx < len(lines):
            text_part = '\n'.join(lines[last_idx:])
            if text_part.strip():
                new_blocks.append(PageBlock(
                    type=BlockType.TEXT,
                    bbox=block.bbox,
                    text=normalize_formula_text(text_part),
                    confidence=block.confidence
                ))

    return new_blocks


def merge_consecutive_formulas(blocks: list[PageBlock]) -> list[PageBlock]:
    if not blocks:
        return blocks

    merged = []
    current_formula = None

    for block in blocks:
        if block.type == BlockType.FORMULA:
            if current_formula is None:
                current_formula = block
            else:
                meta1 = current_formula.metadata.get("formula_meta", {})
                meta2 = block.metadata.get("formula_meta", {})

                if meta1.get("display") and meta2.get("display"):
                    eq1 = meta1.get("eq_number")
                    eq2 = meta2.get("eq_number")

                    if not eq2 or eq1 == eq2:
                        current_formula.text = current_formula.text + " \\\\ " + block.text

                        if current_formula.bbox and block.bbox:
                            current_formula.bbox.x0 = min(current_formula.bbox.x0, block.bbox.x0)
                            current_formula.bbox.y0 = min(current_formula.bbox.y0, block.bbox.y0)
                            current_formula.bbox.x1 = max(current_formula.bbox.x1, block.bbox.x1)
                            current_formula.bbox.y1 = max(current_formula.bbox.y1, block.bbox.y1)
                        elif block.bbox:
                            current_formula.bbox = block.bbox

                        meta1["latex"] = current_formula.text
                        current_formula.metadata["formula_meta"] = meta1
                        continue

                merged.append(current_formula)
                current_formula = block
        else:
            if current_formula is not None:
                merged.append(current_formula)
                current_formula = None
            merged.append(block)

    if current_formula is not None:
        merged.append(current_formula)

    return merged


def reconstruct_document_pages(
    pages: list[PageResult],
    formula_backend: str = "auto",
    recognizer: FormulaRecognizer | None = None,
    crop_callback: Callable[[int, BBox], bytes] | None = None
) -> list[PageResult]:
    """Re-sort blocks within each page by reading order.

    Returns new PageResult objects with sorted blocks; does not mutate input.
    """
    result: list[PageResult] = []
    for page in pages:
        blocks = page.blocks
        if formula_backend in ("l1", "auto", "pix2text"):
            page_crop_cb = None
            if crop_callback:
                page_crop_cb = lambda bbox, p=page.page_num: crop_callback(p, bbox)
            blocks = promote_formulas(blocks, recognizer=recognizer, crop_callback=page_crop_cb)

        sorted_blocks = sort_blocks_reading_order(blocks)
        sorted_blocks = merge_consecutive_formulas(sorted_blocks)
        result.append(
            PageResult(
                page_num=page.page_num,
                blocks=sorted_blocks,
                classification=page.classification,
                needs_ocr=page.needs_ocr,
                width=page.width,
                height=page.height,
            )
        )
    return result
