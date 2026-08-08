"""Unit tests for reproagent.deviation.analyzer."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from reproagent.deviation.analyzer import DeviationAnalyzer
from reproagent.models.backtest import BacktestResult
from reproagent.models.deviation import ToleranceConfig
from reproagent.models.reflection import ReflectionState
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.models.report import ReportedMetrics


@pytest.fixture(scope="module")
def _fv_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Usable factor-value parquet for health gate (non-empty, non-constant)."""
    root = tmp_path_factory.mktemp("fv")
    path = root / "fv.parquet"
    rows = []
    for i in range(30):
        d = date(2020, 1, 1) + timedelta(days=i)
        for j, asset in enumerate(["a", "b", "c"]):
            rows.append({"date": d, "asset": asset, "factor_value": float(i + j)})
    pl.DataFrame(rows).write_parquet(path)
    return path


def _backtest_result(
    ic_mean: float = 0.05,
    ic_ir: float = 0.5,
    long_short_annual_return: float = 0.15,
    sharpe_ratio: float = 1.0,
    max_drawdown: float = 0.1,
    *,
    factor_values_path: Path | None = None,
    turnover: float = 0.1,
    groups: dict[int, float] | None = None,
) -> BacktestResult:
    # module-level path set by fixture via autouse alternative: caller must pass path
    fv = factor_values_path
    if fv is None:
        # fallback for tests that don't inject — create ephemeral usable file
        import tempfile

        tmp = Path(tempfile.mkdtemp()) / "fv.parquet"
        rows = [
            {
                "date": date(2020, 1, 1) + timedelta(days=i),
                "asset": "a",
                "factor_value": float(i),
            }
            for i in range(20)
        ]
        pl.DataFrame(rows).write_parquet(tmp)
        fv = tmp
    return BacktestResult(
        id="bt-1",
        config_id="cfg-1",
        factor_id="f-1",
        engine="polars",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        group_annualized_returns=groups if groups is not None else {0: -0.02, 1: 0.01, 2: 0.05},
        ic_mean=ic_mean,
        ic_ir=ic_ir,
        long_short_annual_return=long_short_annual_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        turnover=turnover,
        factor_values_path=fv,
        equity_curve_path=Path("/tmp/eq.parquet"),
        computed_at=datetime.now(UTC),
    )


def _reported(
    ic_mean: float | None = 0.05,
    ic_ir: float | None = 0.5,
    long_short_return: float | None = 0.15,
    sharpe_ratio: float | None = 1.0,
    max_drawdown: float | None = 0.1,
) -> ReportedMetrics:
    return ReportedMetrics(
        ic_mean=ic_mean,
        ic_ir=ic_ir,
        long_short_return=long_short_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
    )


def _replication_config() -> ReplicationConfig:
    from reproagent.models.factor_spec import FactorInputField, ParsedFactorSpec

    spec = ParsedFactorSpec(
        id="f-1",
        factor_name="momentum_20d",
        factor_name_cn="动量",
        description="d",
        formula="close / Ref(close, 20) - 1",
        input_fields=[FactorInputField(name="close", report_name="收盘价", data_type="price")],
        computation_steps=["pct_change(20)"],
        extraction_confidence=0.9,
    )
    return ReplicationConfig(
        id="cfg-1",
        report_id="r-1",
        factor_specs=[spec],
        engine="polars",
        data_source="local",
        backtest_params=BacktestParams(
            start_date=__import__("datetime").date(2020, 1, 1),
            end_date=__import__("datetime").date(2024, 12, 31),
        ),
        parser_version="1.0.0",
        extraction_model_id="mock",
        created_at=datetime.now(UTC),
    )


def test_analyze_all_within_tolerance_passes() -> None:
    reproduced = _backtest_result()
    reported = _reported()
    tol = ToleranceConfig()
    report = DeviationAnalyzer().analyze(reproduced, reported, tol)
    assert report.passed is True
    assert report.recommend_reflect is False
    assert set(report.metric_deviations) >= {"ic_mean", "sharpe_ratio"}


def test_analyze_ic_breach_fails() -> None:
    reproduced = _backtest_result(ic_mean=0.20)
    reported = _reported(ic_mean=0.05)
    tol = ToleranceConfig()
    report = DeviationAnalyzer().analyze(reproduced, reported, tol)
    assert report.passed is False
    assert report.recommend_reflect is True
    assert abs(report.metric_deviations["ic_mean"] - 0.15) < 1e-9


def test_analyze_sharpe_breach_fails() -> None:
    reproduced = _backtest_result(sharpe_ratio=2.0)
    reported = _reported(sharpe_ratio=1.0)
    tol = ToleranceConfig()
    report = DeviationAnalyzer().analyze(reproduced, reported, tol)
    assert report.passed is False


def test_analyze_no_reported_metrics_passes() -> None:
    reproduced = _backtest_result()
    reported = ReportedMetrics()
    tol = ToleranceConfig()
    report = DeviationAnalyzer().analyze(reproduced, reported, tol)
    assert report.passed is True


def test_analyze_no_reported_metrics_rejects_all_zero_degenerate() -> None:
    """空因子/全零指标不能 vacuous pass。"""
    import tempfile

    empty_path = Path(tempfile.mkdtemp()) / "empty.parquet"
    pl.DataFrame(
        schema={"date": pl.Date, "asset": pl.Utf8, "factor_value": pl.Float64}
    ).write_parquet(empty_path)
    reproduced = _backtest_result(
        ic_mean=0.0,
        ic_ir=0.0,
        long_short_annual_return=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        turnover=0.0,
        groups={},
        factor_values_path=empty_path,
    )
    reported = ReportedMetrics()
    report = DeviationAnalyzer().analyze(reproduced, reported, ToleranceConfig())
    assert report.passed is False
    assert report.recommend_reflect is True


def test_analyze_long_short_relative_tolerance() -> None:
    reproduced = _backtest_result(long_short_annual_return=0.30)
    reported = _reported(long_short_return=0.10)
    tol = ToleranceConfig(long_short_return_rel=0.15)
    report = DeviationAnalyzer().analyze(reproduced, reported, tol)
    assert report.passed is False


def test_classify_root_cause_delegates() -> None:
    from reproagent.models.deviation import RootCause

    reproduced = _backtest_result(ic_mean=0.20)
    reported = _reported(ic_mean=0.05)
    tol = ToleranceConfig()
    analyzer = DeviationAnalyzer()
    report = analyzer.analyze(reproduced, reported, tol)
    cause = analyzer.classify_root_cause(report, _replication_config())
    assert isinstance(cause, RootCause)


def test_should_reflect_true_when_failed_and_in_progress() -> None:
    reproduced = _backtest_result(ic_mean=0.20)
    reported = _reported(ic_mean=0.05)
    tol = ToleranceConfig()
    analyzer = DeviationAnalyzer()
    report = analyzer.analyze(reproduced, reported, tol)
    state = ReflectionState(
        id="s1",
        factor_id="f-1",
        report_id="r-1",
        original_config=_replication_config(),
        max_iterations=3,
        current_iteration=0,
        status="in_progress",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert analyzer.should_reflect(report, state) is True


def test_should_reflect_false_when_passed() -> None:
    reproduced = _backtest_result()
    reported = _reported()
    tol = ToleranceConfig()
    analyzer = DeviationAnalyzer()
    report = analyzer.analyze(reproduced, reported, tol)
    state = ReflectionState(
        id="s1",
        factor_id="f-1",
        report_id="r-1",
        original_config=_replication_config(),
        max_iterations=3,
        current_iteration=0,
        status="in_progress",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert analyzer.should_reflect(report, state) is False


def test_should_reflect_false_when_max_iterations_reached() -> None:
    reproduced = _backtest_result(ic_mean=0.20)
    reported = _reported(ic_mean=0.05)
    tol = ToleranceConfig()
    analyzer = DeviationAnalyzer()
    report = analyzer.analyze(reproduced, reported, tol)
    state = ReflectionState(
        id="s1",
        factor_id="f-1",
        report_id="r-1",
        original_config=_replication_config(),
        max_iterations=3,
        current_iteration=3,
        status="in_progress",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert analyzer.should_reflect(report, state) is False


def test_should_reflect_false_when_converged() -> None:
    reproduced = _backtest_result(ic_mean=0.20)
    reported = _reported(ic_mean=0.05)
    tol = ToleranceConfig()
    analyzer = DeviationAnalyzer()
    report = analyzer.analyze(reproduced, reported, tol)
    state = ReflectionState(
        id="s1",
        factor_id="f-1",
        report_id="r-1",
        original_config=_replication_config(),
        max_iterations=3,
        current_iteration=1,
        status="converged",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert analyzer.should_reflect(report, state) is False
