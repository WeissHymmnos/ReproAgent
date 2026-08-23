"""Factor names with slashes must not create nested wiki paths."""

from __future__ import annotations

from pathlib import Path

from reproagent.library.wiki_writer import safe_factor_filename


def test_safe_filename_replaces_slash() -> None:
    assert "/" not in safe_factor_filename("E/P")
    assert "\\" not in safe_factor_filename("EP\\P")
    assert safe_factor_filename("E/P") == "E_P"
    assert safe_factor_filename("Earnings/Price") == "Earnings_Price"


def test_index_writer_includes_ic_column(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from reproagent.library.index_writer import IndexWriter
    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.persistence.paths import AppPaths

    paths = AppPaths(data_dir=tmp_path / "data")
    paths.ensure_layout()
    writer = IndexWriter(paths)
    factor = FactorDefinition(
        id="id-ix",
        spec_id="s",
        name="idx_mom",
        name_cn="指数动量",
        style="momentum",
        formula="close",
        input_fields=["close"],
        universe="all",
        rebalance_frequency="monthly",
    )
    entry = FactorLibraryEntry(
        id="e-ix",
        factor=factor,
        report_id="r",
        config_id="c",
        backtest_result_id="b",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="abcdef012345",
        tags=[],
        created_at=datetime.now(UTC),
        metrics={"ic": 0.1234},
    )
    writer.update([entry])
    text = paths.wiki_index.read_text(encoding="utf-8")
    assert "| IC |" in text
    assert "0.123" in text
    assert "idx_mom" in text or "指数动量" in text


def test_safe_filename_empty() -> None:
    assert safe_factor_filename("") == "factor"
    assert safe_factor_filename("  ///  ") == "factor"
