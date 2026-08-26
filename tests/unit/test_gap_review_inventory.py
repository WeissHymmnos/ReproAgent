"""gap-review.md 里的清单要和现货代码对得上。"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
README_EN = ROOT / "README_EN.md"
GAP_REVIEW = ROOT / "docs" / "gap-review.md"


def test_data_source_literal_is_the_four_shipped_backends() -> None:
    from reproagent.settings import Settings

    values = set(get_args(Settings.model_fields["data_source"].annotation))
    assert values == {"local", "ricequant", "qlib", "tushare"}
    assert Settings().data_source == "local"


def test_engine_operator_registry_meets_readme_55plus() -> None:
    from reproagent.reproducer.polars_engine import _CONTEXT, _OPERATOR_WHITELIST

    ops = {name for name in _CONTEXT if name not in {"pl", "Const"}}
    assert ops == set(_OPERATOR_WHITELIST)
    assert len(ops) >= 55
    # Core mechanics named in the gap review must be the real functions.
    for required in ("Rank", "Ref", "Delta", "GroupNeutral", "Ts_Rank", "Winsorize"):
        assert required in ops
        assert callable(_CONTEXT[required])


def test_group_neutral_is_cross_sectional_demean_not_industry() -> None:
    import polars as pl

    from reproagent.reproducer.polars_engine import GroupNeutral

    df = pl.DataFrame(
        {
            "date": ["2020-01-02"] * 3,
            "asset": ["a", "b", "c"],
            "x": [1.0, 2.0, 3.0],
        }
    ).with_columns(GroupNeutral(pl.col("x")).alias("n"))
    # x - mean(date) => [-1, 0, 1]
    assert df["n"].to_list() == pytest.approx([-1.0, 0.0, 1.0])


def test_cli_entry_points_match_help_inventory() -> None:
    from typer.main import get_command

    from reproagent.cli import app

    click_app = get_command(app)
    names = set(click_app.list_commands(None))
    assert names == {
        "ingest",
        "reproduce",
        "text",
        "library",
        "review",
        "tui",
        "serve",
        "benchmark",
        "mcp",
        "decay",
        "runs",
        "market",
    }


def test_readme_states_in_mission_and_non_goals() -> None:
    text = README.read_text(encoding="utf-8")
    assert "## 能做什么,不能做什么" in text
    assert "实盘交易" in text
    assert "组合优化和风险模型" in text
    assert "Polars 表达式引擎,55+ 算子" in text
    assert "`local` / `ricequant` / `qlib` / `tushare`" in text
    assert "`qlib`" in text
    assert "uv sync --extra qlib" in text
    en = README_EN.read_text(encoding="utf-8")
    assert "Live trading" in en
    assert "Portfolio optimization or risk models" in en


def test_gap_review_pins_peers_and_matrix_groups() -> None:
    text = GAP_REVIEW.read_text(encoding="utf-8")
    assert GAP_REVIEW.is_file()
    for peer in (
        "WorldQuant BRAIN",
        "Microsoft Qlib",
        "QuantConnect LEAN",
        "Two Sigma Venn",
    ):
        assert peer in text
    for url in (
        "https://www.worldquant.com/brain/",
        "https://github.com/microsoft/qlib",
        "https://www.lean.io/",
        "https://www.twosigma.com/articles/introducing-the-two-sigma-factor-lens/",
    ):
        assert url in text
    for group in (
        "组 (a)",
        "组 (b)",
        "组 (c)",
        "组 (d)",
        "组 (e)",
    ):
        assert group in text
    assert "任务内" in text
    assert "任务外" in text
    assert "不要指望它做的事" in text


def test_lookahead_negative_ref_rejected_by_shipped_detector() -> None:
    from reproagent.reproducer.lookahead_detector import detect_lookahead

    report = detect_lookahead("Ref(close, -1)")
    assert report.has_lookahead is True
    assert any(f.severity == "error" for f in report.findings)
