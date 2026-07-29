"""Text-layer table extraction — zero OCR/structure load path."""

from pathlib import Path

import fitz
import pytest

from finreportparser.extract.text_tables import extract_tables_from_page
from finreportparser.fusion.table_quality import score_table
from finreportparser.fusion.table_repair import repair_table_gfm


def _sample_pdf() -> Path:
    candidates = [
        Path.home() / "Documents/reproagent/【转债专题报告】转债量化手册：因子投资实践.pdf",
        Path.home() / "Documents/finpdfpro/【转债专题报告】转债量化手册：因子投资实践.pdf",
    ]
    for p in candidates:
        if p.is_file():
            return p
    pytest.skip("sample research PDF not available")


def test_extract_tables_from_real_research_page() -> None:
    """Real digital PDF page must yield repaired GFM tables without Paddle."""
    pdf = _sample_pdf()
    doc = fitz.open(str(pdf))
    # Page 9 (1-based) has 图表5 factor backtest table
    page = doc[8]
    extracts = extract_tables_from_page(page)
    doc.close()
    assert extracts, "expected at least one text-layer table on page 9"
    best = max(extracts, key=lambda e: score_table(repair_table_gfm(e.gfm).gfm))
    repaired = repair_table_gfm(best.gfm)
    gfm = repaired.gfm
    # Must look like a metric table
    assert "YTM" in gfm or "展示" in gfm or "%" in gfm
    assert score_table(gfm) >= 0.35
    # Header should not be a single glued blob
    header = gfm.split("\n")[0]
    assert header.count("|") >= 4


def test_extract_empty_on_blank_page() -> None:
    doc = fitz.open()
    page = doc.new_page()
    assert extract_tables_from_page(page) == []
    doc.close()
