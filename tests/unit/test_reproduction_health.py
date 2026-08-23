"""Honest pass-gate: null/empty factors and all-zero metrics must not pass."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from reproagent.deviation.analyzer import DeviationAnalyzer
from reproagent.models.backtest import BacktestResult
from reproagent.models.deviation import ToleranceConfig
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.models.report import ReportedMetrics
from reproagent.reproducer.health import (
    factor_values_are_usable,
    is_healthy_reproduction,
    metrics_are_non_degenerate,
)
from reproagent.reproducer.polars_engine import PolarsEngine


def _usable_fv(path: Path, n: int = 40) -> Path:
    rows = []
    for i in range(n):
        d = date(2020, 1, 1) + timedelta(days=i)
        for j, a in enumerate(["x", "y"]):
            rows.append({"date": d, "asset": a, "factor_value": float(i * 0.1 + j)})
    pl.DataFrame(rows).write_parquet(path)
    return path


def _result(
    path: Path,
    *,
    ic: float = 0.02,
    sharpe: float = 0.5,
    mdd: float = 0.1,
    ls: float = 0.05,
    turnover: float = 0.2,
    groups: dict | None = None,
) -> BacktestResult:
    return BacktestResult(
        id="bt",
        config_id="c",
        factor_id="f",
        engine="polars",
        start_date=date(2020, 1, 1),
        end_date=date(2021, 1, 1),
        group_annualized_returns=groups if groups is not None else {0: -0.01, 4: 0.03},
        ic_mean=ic,
        ic_ir=0.3,
        long_short_annual_return=ls,
        sharpe_ratio=sharpe,
        max_drawdown=mdd,
        turnover=turnover,
        factor_values_path=path,
        equity_curve_path=path.parent / "eq.parquet",
        computed_at=datetime.now(UTC),
    )


def test_empty_factor_values_not_usable(tmp_path: Path) -> None:
    p = tmp_path / "empty.parquet"
    pl.DataFrame(
        schema={"date": pl.Date, "asset": pl.Utf8, "factor_value": pl.Float64}
    ).write_parquet(p)
    assert factor_values_are_usable(p) is False


def test_constant_factor_values_not_usable(tmp_path: Path) -> None:
    p = tmp_path / "const.parquet"
    rows = [
        {"date": date(2020, 1, 1) + timedelta(days=i), "asset": "a", "factor_value": 1.0}
        for i in range(30)
    ]
    pl.DataFrame(rows).write_parquet(p)
    assert factor_values_are_usable(p) is False


def test_all_zero_metrics_degenerate(tmp_path: Path) -> None:
    p = _usable_fv(tmp_path / "fv.parquet")
    r = _result(p, ic=0.0, sharpe=0.0, mdd=0.0, ls=0.0, turnover=0.0, groups={})
    assert metrics_are_non_degenerate(r) is False
    assert is_healthy_reproduction(r) is False


def test_healthy_result_passes(tmp_path: Path) -> None:
    p = _usable_fv(tmp_path / "fv.parquet")
    r = _result(p)
    assert is_healthy_reproduction(r) is True


def test_analyzer_rejects_zero_metrics_without_gt(tmp_path: Path) -> None:
    p = tmp_path / "empty.parquet"
    pl.DataFrame(
        schema={"date": pl.Date, "asset": pl.Utf8, "factor_value": pl.Float64}
    ).write_parquet(p)
    r = _result(p, ic=0.0, sharpe=0.0, mdd=0.0, ls=0.0, turnover=0.0, groups={})
    report = DeviationAnalyzer().analyze(r, ReportedMetrics(), ToleranceConfig())
    assert report.passed is False


def test_ast_failure_falls_back_to_close_not_null() -> None:
    """Missing field should not produce empty/null panel when fallback allowed."""
    cfg = ReplicationConfig(
        id="t",
        report_id="r",
        factor_specs=[],
        engine="polars",
        data_source="local",
        backtest_params=BacktestParams(start_date=date(2024, 1, 1), end_date=date(2024, 1, 10)),
        parser_version="1.0.0",
        extraction_model_id="test",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(cfg, allow_formula_fallback=True)
    data = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 2), date(2024, 1, 3)] * 2,
            "ts_code": ["a", "a", "b", "b"],
            "open": [1.0, 1.1, 2.0, 2.1],
            "high": [1.0, 1.1, 2.0, 2.1],
            "low": [1.0, 1.1, 2.0, 2.1],
            "close": [10.0, 11.0, 20.0, 22.0],
            "volume": [100.0] * 4,
        }
    )
    fdef = FactorDefinition(
        id="f",
        spec_id="f",
        name="mktcap",
        name_cn="市值",
        style="size",
        formula="Log(total_market_cap)",  # missing column → fallback to close
        input_fields=["total_market_cap"],
        universe="csi300",
        rebalance_frequency="monthly",
    )
    out = engine.compute(fdef, "csi300", date(2024, 1, 1), date(2024, 1, 10), data=data)
    assert out.height >= 1
    assert out["factor_value"].null_count() == 0
    assert float(out["factor_value"].std() or 0) > 0
