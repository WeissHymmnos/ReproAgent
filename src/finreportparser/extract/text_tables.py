"""Extract tables from PDF text layer (zero GPU/OCR load).

Uses PyMuPDF word boxes → row clustering → column alignment → GFM.
This is the primary quality path for digital (non-scanned) Chinese research PDFs
and is dramatically faster/lighter than PP-Structure.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz

from finreportparser.types import BBox, TableExtract


@dataclass
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def _cluster_rows(words: list[_Word], y_tol: float = 4.0) -> list[list[_Word]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.cy, w.x0))
    rows: list[list[_Word]] = [[ordered[0]]]
    for w in ordered[1:]:
        if abs(w.cy - rows[-1][0].cy) <= y_tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w.x0)
    return rows


def _column_breaks(rows: list[list[_Word]], min_gap: float = 4.0) -> list[float]:
    """Infer vertical column split x-positions from inter-word gaps.

    Uses a lower min_gap and lower hit threshold so dense financial tables
    (many narrow numeric columns) still produce enough splits.
    """
    gaps: list[tuple[float, float]] = []  # (gap_mid, gap_size)
    for row in rows:
        for a, b in zip(row, row[1:], strict=False):
            gap = b.x0 - a.x1
            if gap >= min_gap:
                gaps.append(((a.x1 + b.x0) / 2, gap))
    if not gaps:
        return []
    # Cluster gap midpoints (tighter cluster radius for narrow cols)
    gaps.sort(key=lambda g: g[0])
    clusters: list[list[float]] = [[gaps[0][0]]]
    for mid, _sz in gaps[1:]:
        if abs(mid - clusters[-1][-1]) < 8:
            clusters[-1].append(mid)
        else:
            clusters.append([mid])
    # Keep clusters that appear often enough (at least ~25% of rows)
    min_hits = max(2, len(rows) // 4)
    breaks = []
    for cl in clusters:
        if len(cl) >= min_hits:
            breaks.append(sum(cl) / len(cl))
    return sorted(breaks)


def _assign_cells(row: list[_Word], breaks: list[float]) -> list[str]:
    if not breaks:
        return [" ".join(w.text for w in row)]
    cells: list[list[str]] = [[] for _ in range(len(breaks) + 1)]
    for w in row:
        idx = 0
        while idx < len(breaks) and w.cx > breaks[idx]:
            idx += 1
        cells[idx].append(w.text)
    return [" ".join(c).strip() for c in cells]


def _rows_to_gfm(grid: list[list[str]]) -> str:
    if not grid:
        return ""
    # Normalize column count
    n = max(len(r) for r in grid)
    if n < 2:
        return ""
    norm = []
    for r in grid:
        rr = list(r) + [""] * (n - len(r))
        norm.append(rr[:n])
    lines = ["| " + " | ".join(norm[0]) + " |", "| " + " | ".join(["---"] * n) + " |"]
    for r in norm[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _is_tableish(grid: list[list[str]]) -> bool:
    if len(grid) < 2:
        return False
    cols = [len(r) for r in grid]
    if max(cols) < 3:
        return False
    # Majority of rows should have similar width
    from collections import Counter

    c = Counter(cols)
    mode_c, hits = c.most_common(1)[0]
    if mode_c < 3 or hits < max(2, len(grid) // 2):
        return False
    # Numeric density helps distinguish tables from prose
    cells = [cell for r in grid for cell in r if cell]
    if not cells:
        return False
    numish = sum(1 for c in cells if any(ch.isdigit() for ch in c))
    return numish / len(cells) >= 0.25


def extract_tables_from_page(
    page: fitz.Page,
    *,
    y_tol: float = 4.0,
    min_gap: float = 8.0,
    min_rows: int = 2,
) -> list[TableExtract]:
    """Extract table candidates purely from the text layer of *page*."""
    raw = page.get_text("words") or []
    words = [
        _Word(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
        for w in raw
        if w[4] and str(w[4]).strip()
    ]
    if len(words) < 6:
        return []

    rows = _cluster_rows(words, y_tol=y_tol)
    if len(rows) < min_rows:
        return []

    # Split into vertical bands of consecutive multi-word rows (table regions)
    regions: list[list[list[_Word]]] = []
    current: list[list[_Word]] = []
    for row in rows:
        if len(row) >= 2:
            current.append(row)
        else:
            if len(current) >= min_rows:
                regions.append(current)
            current = []
    if len(current) >= min_rows:
        regions.append(current)

    extracts: list[TableExtract] = []
    for region in regions:
        breaks = _column_breaks(region, min_gap=min_gap)
        if len(breaks) < 1:
            continue
        grid = [_assign_cells(r, breaks) for r in region]
        # Drop empty trailing columns
        while grid and all(not r[-1] for r in grid) and len(grid[0]) > 2:
            grid = [r[:-1] for r in grid]
        # Drop leading caption rows (e.g. "图表5： 主要单因子回测表现")
        while grid and sum(1 for c in grid[0] if c) <= 2 and len(grid) > 2:
            grid = grid[1:]
        if not _is_tableish(grid):
            continue
        gfm = _rows_to_gfm(grid)
        if not gfm:
            continue
        # BBox of region
        x0 = min(w.x0 for r in region for w in r)
        y0 = min(w.y0 for r in region for w in r)
        x1 = max(w.x1 for r in region for w in r)
        y1 = max(w.y1 for r in region for w in r)
        extracts.append(
            TableExtract(
                gfm=gfm,
                bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                html=None,
            )
        )
    return extracts
