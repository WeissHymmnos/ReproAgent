"""Table quality scoring — used as accept/reject gate after repair."""

from __future__ import annotations

import re

from finreportparser.fusion.table_repair import header_looks_glued


def _parse_rows(gfm: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in gfm.strip().split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and all(re.match(r"^:?-+:?$", c or "-") for c in cells):
            continue
        rows.append(cells)
    return rows


def score_table(gfm: str) -> float:
    if not gfm or not gfm.strip():
        return 0.0

    rows = _parse_rows(gfm)
    if len(rows) < 2:
        return 0.0

    header_row = rows[0]
    data_rows = rows[1:]
    num_cols = len(header_row)
    num_data_rows = len(data_rows)

    if num_data_rows < 1 or num_cols < 2:
        return 0.0

    total_cells = 0
    empty_cells = 0
    total_text_length = 0

    for row in data_rows:
        for cell in row:
            total_cells += 1
            text_len = len(cell)
            total_text_length += text_len
            if text_len == 0:
                empty_cells += 1
            if "请务必阅读正文之后" in cell:
                return 0.0

    if data_rows and data_rows[0]:
        first_cell = data_rows[0][0]
        contamination_keywords = ["HAITONG", "海通证券", "证券研究报告", "金融工程研究"]
        if any(keyword in first_cell for keyword in contamination_keywords):
            return 0.0

    if total_cells == 0:
        return 0.0

    mean_cell_length = total_text_length / total_cells
    if mean_cell_length > 100:
        return 0.0

    empty_ratio = empty_cells / total_cells
    if empty_ratio > 0.7:
        return 0.0

    score = 1.0
    score -= empty_ratio * 0.2
    score -= (mean_cell_length / 100) * 0.2

    # --- Robustness penalties ---
    # Glued header still present after repair → heavy penalty
    if header_looks_glued(header_row):
        score -= 0.45

    # Header vs data width mismatch
    data_widths = [len(r) for r in data_rows]
    if data_widths:
        median_w = sorted(data_widths)[len(data_widths) // 2]
        if abs(median_w - num_cols) >= 2:
            score -= 0.25
        elif abs(median_w - num_cols) == 1:
            score -= 0.1

    # Too many empty header cells (classic OCR glue remnant)
    empty_header = sum(1 for c in header_row if not c)
    if empty_header >= max(2, num_cols // 2):
        score -= 0.3

    # Single header cell longer than 18 chars while many columns → likely glue
    for c in header_row:
        if len(re.sub(r"\s+", "", c)) >= 18 and num_cols >= 4:
            score -= 0.2
            break

    # Known garbage OCR patterns that indicate unrepaired text
    garbage_markers = ("收孟", "波暗", "W撒", "因于IC", "超收盖", "温价率", "讨级")
    blob = "|".join(header_row + [c for r in data_rows[:3] for c in r])
    hits = sum(1 for m in garbage_markers if m in blob)
    if hits:
        score -= 0.12 * hits

    return max(0.0, min(1.0, score))


def is_acceptable_table(gfm: str) -> bool:
    """Accept tables that clear a modest quality bar after repair."""
    return score_table(gfm) >= 0.35
