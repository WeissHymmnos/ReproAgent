"""End-to-end lite profile on the real research PDF (shipped entry points)."""

from __future__ import annotations

from pathlib import Path

import pytest

from finreportparser.config import load_config
from finreportparser.pipeline.orchestrator import parse_pdf
from finreportparser.types import BlockType


def _pdf() -> Path:
    p = Path.home() / "Documents/reproagent/【转债专题报告】转债量化手册：因子投资实践.pdf"
    if not p.is_file():
        pytest.skip("sample PDF missing")
    return p


def test_lite_profile_parses_real_pdf_fast_and_clean(tmp_path: Path) -> None:
    """Drive real parse_pdf with profile=lite; assert tables + no header/footer."""
    cfg = load_config(
        overrides={
            "profile": "lite",
            "out_dir": str(tmp_path),
            "resume": False,
            "cache_dir": str(tmp_path / ".cache"),
        }
    )
    assert cfg.allow_structure is False
    assert cfg.allow_vlm is False
    assert cfg.prefer_text_tables is True

    doc = parse_pdf(_pdf(), cfg, out_dir=tmp_path, resume=False)
    assert len(doc.pages) == 36

    tables = [
        b
        for p in doc.pages
        for b in p.blocks
        if b.type == BlockType.TABLE and b.text
    ]
    assert len(tables) >= 20
    # All lite tables must come from text layer (no structure engine)
    for b in tables:
        src = (b.metadata or {}).get("table_source")
        assert src == "text_layer", f"unexpected table source {src}"

    # Find YTM factor row with split columns
    found = False
    for b in tables:
        for line in (b.text or "").splitlines():
            if "YTM" in line and "14.17%" in line:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if (
                    len(cells) == 9
                    and "7.24%" in cells
                    and "6.90%" in cells
                    and "1.17 7.24%" not in line
                ):
                    found = True
                    break
    assert found, "expected repaired 9-col YTM row from text-layer tables"

    # Headers/footers stripped
    for p in doc.pages:
        for b in p.blocks:
            t = (b.text or "").strip()
            assert t != "固收研究"
            assert not t.startswith("免责声明和披露以及分析师声明")
