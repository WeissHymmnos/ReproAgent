"""Generic table repair robustness tests (no model / no PDF)."""

from finreportparser.fusion.table_quality import is_acceptable_table, score_table
from finreportparser.fusion.table_repair import (
    apply_ocr_phrase_fixes,
    header_looks_glued,
    repair_table_gfm,
)


def test_phrase_fixes_premium_and_rating() -> None:
    s = apply_ocr_phrase_fixes("纯温价率因子 讨级、期限、规模 绝时价格")
    assert "纯债溢价率因子" in s
    assert "评级" in s
    assert "绝对价格" in s


def test_detect_glued_header() -> None:
    header = [
        "展示名称",
        "中性化处理",
        "年化收孟率平化波暗率最大W撒夏普比率因于ICRankIC超收盖",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    assert header_looks_glued(header)


def test_repair_glued_metric_header() -> None:
    """Classic failure mode: multi-metric header glued into one cell."""
    gfm = """| 展示名称 | 中性化处理 | 年化收孟率平化波暗率最大W撒夏普比率因于ICRankIC超收盖 |  |  |  |  |  |  |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| YTM | 讨级、期限、规模 | 14.17% | 11.99% | -9.16% | 1.17 | 7.24% | 10.11% | 6.90% |
| 纯温价率因子 | 讨级、期限、规模 | 14.98% | 12.82% | -13.87% | 1.16 | 8.08% | 12.83% | 7.88% |
| 绝时价格 | 行业、信用评线、制余期限、成交相、换手率 | 9.07% | 12.29% | -16.33% | 0.74 | 6.75% | 12.07% | 2.16% |
"""
    raw_score = score_table(gfm)
    result = repair_table_gfm(gfm)
    assert result.repaired
    assert any("split_glued" in a or "resplit" in a or "phrase" in a for a in result.actions)

    # Header should expose separate metric columns
    header_line = result.gfm.split("\n")[0]
    assert "年化收益率" in header_line
    assert "年化波动率" in header_line
    assert "最大回撤" in header_line
    assert "超额收益" in header_line
    assert "收孟" not in header_line
    assert "W撒" not in header_line

    # Body OCR phrases fixed
    assert "纯债溢价率因子" in result.gfm
    assert "绝对价格" in result.gfm
    assert "评级" in result.gfm
    assert "剩余期限" in result.gfm

    fixed_score = score_table(result.gfm)
    assert fixed_score > raw_score
    assert is_acceptable_table(result.gfm)


def test_repair_merged_numeric_cells() -> None:
    gfm = """| 名称 | 收益 | 回撤 |
| --- | --- | --- |
| A | 13.41% -17.69% | 0.91 |
"""
    # After repair with 3-col header, merged "13.41% -17.69%" should expand if short
    result = repair_table_gfm(gfm)
    # At minimum phrase layer should not crash
    assert result.gfm
    assert "A" in result.gfm


def test_clean_table_not_destroyed() -> None:
    gfm = """| 展示名称 | 中性化处理 | 年化收益率 | 年化波动率 | 最大回撤 | 夏普比率 | 因子IC | RankIC | 超额收益 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| YTM | 评级、期限、规模 | 14.17% | 11.99% | -9.16% | 1.17 | 7.24% | 10.11% | 6.90% |
| 纯债溢价率因子 | 评级、期限、规模 | 14.98% | 12.82% | -13.87% | 1.16 | 8.08% | 12.83% | 7.88% |
"""
    result = repair_table_gfm(gfm)
    assert "YTM" in result.gfm
    assert "纯债溢价率因子" in result.gfm
    assert is_acceptable_table(result.gfm)
    # Column count preserved
    header_cols = result.gfm.split("\n")[0].count("|") - 1
    assert header_cols == 9
