import logging
from collections.abc import Callable
from typing import Any

from finreportparser.fusion.rules_numbers import check_table_sum_consistency, parse_numbers
from finreportparser.types import BlockType, DocumentResult

logger = logging.getLogger(__name__)

def is_total_cell(text: str) -> bool:
    text_lower = text.lower()
    for kw in ["合计", "总计", "总额", "小计", "total", "sum", "subtotal"]:
        if kw in text_lower:
            return True
    return False

def check_table_consistency_in_markdown(markdown_text: str) -> list[dict[str, Any]]:
    warnings = []
    if not markdown_text:
        return warnings

    lines = [line.strip() for line in markdown_text.strip().split('\n') if line.strip()]
    if not lines:
        return warnings

    rows = []
    for line in lines:
        if line.startswith('|') and set(
            line.replace('|', '').replace('-', '').replace(' ', '').replace(':', '')
        ) == set():
            continue
        if '|' not in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        rows.append(cells)

    if len(rows) < 3:
        return warnings

    header = rows[0]
    num_cols = len(header)

    for i in range(1, len(rows)):
        row = rows[i]
        if len(row) != num_cols:
            continue

        is_total = False
        for cell in row:
            if is_total_cell(cell):
                is_total = True
                break

        if not is_total:
            continue

        addend_rows = []
        for j in range(1, i):
            j_is_total = False
            for cell in rows[j]:
                if is_total_cell(cell):
                    j_is_total = True
                    break
            if not j_is_total and len(rows[j]) == num_cols:
                addend_rows.append(rows[j])

        if not addend_rows:
            continue

        for col_idx in range(1, num_cols):
            col_header = header[col_idx] if col_idx < len(header) else f"Column {col_idx}"

            total_cell = row[col_idx]
            total_spans = parse_numbers(total_cell)
            if not total_spans:
                continue
            total_val = total_spans[0].value

            addend_vals = []
            has_any_number = False
            for addend_row in addend_rows:
                cell_val = addend_row[col_idx]
                spans = parse_numbers(cell_val)
                if spans:
                    addend_vals.append(spans[0].value)
                    has_any_number = True
                else:
                    addend_vals.append(0.0)

            if not has_any_number:
                continue

            if not check_table_sum_consistency(addend_vals, total_val):
                warnings.append({
                    "column_header": col_header,
                    "expected_total": sum(addend_vals),
                    "actual_total": total_val
                })
    return warnings

def reprocess_low_conf(doc: DocumentResult, ocr_fn: Callable[[str], str] | None = None) -> DocumentResult:
    if ocr_fn is None:
        import importlib.util
        import sys
        has_paddleocr = False
        if "paddleocr" in sys.modules:
            has_paddleocr = True
        else:
            try:
                has_paddleocr = importlib.util.find_spec("paddleocr") is not None
            except ValueError:
                has_paddleocr = False
        if has_paddleocr:
            def default_cleanup(text: str) -> str:
                return text.strip()
            ocr_fn = default_cleanup
        else:
            logger.warning("PaddleOCR not available, skipping OCR reprocess")
            return doc

    for page in doc.pages:
        for block in page.blocks:
            if block.confidence is not None and block.confidence < 0.8:
                if block.metadata and block.metadata.get("reprocessed"):
                    continue

                if block.text:
                    block.text = ocr_fn(block.text)

                if block.metadata is None:
                    block.metadata = {}
                block.metadata["reprocessed"] = True

    return doc

def run_quality_checks(doc: DocumentResult) -> dict[str, Any]:
    low_conf_count = 0
    for page in doc.pages:
        for block in page.blocks:
            if block.confidence is not None and block.confidence < 0.8:
                low_conf_count += 1

    mermaid_invalid_count = 0
    for mermaid in doc.mermaid:
        code_strip = mermaid.code.strip()
        if (
            not code_strip.startswith("graph")
            and not code_strip.startswith("pie")
            and not code_strip.startswith("sequenceDiagram")
        ):
            mermaid_invalid_count += 1

    metrics_count = len(doc.metrics)

    table_sum_warnings = []
    for page in doc.pages:
        for block in page.blocks:
            if block.type == BlockType.TABLE and block.text:
                warnings = check_table_consistency_in_markdown(block.text)
                for w in warnings:
                    w["page_num"] = page.page_num
                    table_sum_warnings.append(w)

    quality_dict = {
        "low_conf_count": low_conf_count,
        "mermaid_invalid_count": mermaid_invalid_count,
        "metrics_count": metrics_count,
        "table_sum_warnings": table_sum_warnings
    }

    doc.quality = quality_dict

    if low_conf_count > 10:
        doc = reprocess_low_conf(doc)

    return quality_dict
