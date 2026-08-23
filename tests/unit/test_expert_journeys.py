"""Regression tests for defects found by expert-user journeys."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.models.report import ResearchReport
from reproagent.parser.config_builder import apply_backtest_kwargs, backtest_params_token
from reproagent.parser.layout_extractor import LayoutExtractor
from reproagent.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_source="local",
        local_data_path=Path("tests/fixtures/test_data"),
        data_dir=tmp_path / "data",
        allow_mock_llm=True,
    )


def _report(pdf: Path) -> ResearchReport:
    return ResearchReport(
        id="rep-expert-1",
        file_path=pdf,
        file_hash="hash-expert-1",
        title="minimal",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )


def test_validate_expression_catches_unary_minus_ref() -> None:
    """MCP validate_expression must reject Ref(close, -1); -1 is AST UnaryOp."""
    from reproagent.reproducer.polars_engine import validate_expression

    bad = validate_expression("Ref(close, -1)")
    assert bad["valid"] is False
    assert any("negative window" in e for e in bad["errors"])
    assert not any("without lag" in w for w in bad["warnings"])

    ok = validate_expression("close / Ref(close, 5) - 1")
    assert ok["valid"] is True
    lag_warnings = [w for w in ok["warnings"] if "without lag" in w]
    assert len(lag_warnings) == 1


def test_reproduce_text_same_body_reuses_report_id(tmp_path: Path) -> None:
    from reproagent.pipeline import reproduce_text

    settings = _settings(tmp_path)
    body = "动量因子：close / Ref(close, 5) - 1"
    first = reproduce_text(body, settings, title="a")
    second = reproduce_text(body, settings, title="b")
    assert first is not None and second is not None
    assert first["report_id"] == second["report_id"]


def test_reproduce_same_pdf_reuses_report_id(tmp_path: Path) -> None:
    from reproagent.pipeline import reproduce_report

    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    if not pdf.exists():
        pytest.skip("fixture pdf missing")
    settings = _settings(tmp_path)
    first = reproduce_report(pdf, settings)
    second = reproduce_report(pdf, settings)
    assert first is not None and second is not None
    assert first["report_id"] == second["report_id"]


def test_missing_local_data_does_not_enqueue_review(tmp_path: Path) -> None:
    from pydantic import SecretStr
    from sqlmodel import Session, select

    from reproagent.pipeline import reproduce_report
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.tables import ManualReviewQueueTable

    empty = tmp_path / "no-prices"
    empty.mkdir()
    settings = Settings(
        data_source="local",
        local_data_path=empty,
        data_dir=tmp_path / "data",
        allow_mock_llm=True,
        llm_api_key=SecretStr(""),
    )
    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    if not pdf.exists():
        pytest.skip("fixture pdf missing")
    out = reproduce_report(pdf, settings)
    assert out.get("status") in {"error", "partial"}
    engine = get_engine(settings.db_path)
    init_db(engine)
    with Session(engine) as session:
        pending = session.exec(
            select(ManualReviewQueueTable).where(ManualReviewQueueTable.status == "pending")
        ).all()
    assert pending == []


def test_reproduce_help_mentions_markdown() -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app

    result = CliRunner().invoke(app, ["reproduce", "--help"])
    assert result.exit_code == 0
    assert "Markdown" in result.output


def test_text_cli_rejects_binary_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    if not pdf.exists():
        pytest.skip("fixture pdf missing")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["text", "-f", str(pdf)])
        assert result.exit_code == 1
        out = result.output or ""
        assert "not UTF-8" in out
        assert "Traceback" not in out
    finally:
        get_settings.cache_clear()


def test_mcp_cli_without_fastmcp_is_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from typer.testing import CliRunner

    from reproagent.cli import app

    real_import = builtins.__import__

    def _no_mcp(name: str, *args: object, **kwargs: object) -> object:
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"No module named {name!r} (simulated)")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_mcp)

    result = CliRunner().invoke(app, ["mcp"])
    assert result.exit_code == 1
    out = (result.output or "") + (getattr(result, "stderr", None) or "")
    assert "unavailable" in out.lower() or "mcp" in out.lower()
    assert "Traceback" not in out


def test_echo_pipeline_cli_fails_on_invalid_status() -> None:
    import typer

    from reproagent.cli import echo_pipeline_cli

    echo_pipeline_cli("reproduce", {"status": "passed", "factor_count": 1})
    echo_pipeline_cli("reproduce", {"status": "review_enqueued", "factor_count": 0})
    with pytest.raises(typer.Exit) as ei:
        echo_pipeline_cli("reproduce", {"status": "invalid", "factor_count": 0})
    assert ei.value.exit_code == 1


def test_invalid_reproduce_does_not_duplicate_review(
    tmp_path: Path,
) -> None:
    from sqlmodel import Session, select

    from reproagent.pipeline import reproduce_report
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.tables import ManualReviewQueueTable

    settings = _settings(tmp_path)
    junk = tmp_path / "x.csv"
    junk.write_text("a,b\n1,2\n", encoding="utf-8")
    first = reproduce_report(junk, settings)
    second = reproduce_report(junk, settings)
    assert first["status"] == "invalid"
    assert second["report_id"] == first["report_id"]
    engine = get_engine(settings.db_path)
    init_db(engine)
    with Session(engine) as session:
        pending = session.exec(
            select(ManualReviewQueueTable).where(ManualReviewQueueTable.status == "pending")
        ).all()
    # junk/invalid input is a system-capability failure, not a human review item
    assert pending == []


def test_reproduce_cli_invalid_csv_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    csv = tmp_path / "not-a-report.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["reproduce", str(csv)])
        assert result.exit_code == 1, result.output
        assert "reproduce ok" not in (result.output or "")
        assert "invalid" in (result.output or "")
    finally:
        get_settings.cache_clear()


def test_layout_extract_after_vendored_parser_preload(tmp_path: Path) -> None:
    """Journey 1: extract must not crash if the 0.2.0 vendor is already imported."""
    import finreportparser  # noqa: F401 — preload whatever is on sys.path first

    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    if not pdf.exists():
        pytest.skip("fixture pdf missing")
    extractor = LayoutExtractor(settings=_settings(tmp_path))
    md = extractor.extract(_report(pdf))
    assert isinstance(md, str)
    assert len(md.strip()) > 20


def test_reproduce_report_dispatches_markdown_to_text_path(tmp_path: Path) -> None:
    """CLI/TUI `reproduce foo.md` must not treat Markdown as a broken PDF."""
    from reproagent.pipeline import reproduce_report

    md = tmp_path / "momentum.md"
    md.write_text("动量因子：close / Ref(close, 5) - 1\n", encoding="utf-8")
    result = reproduce_report(md, _settings(tmp_path))
    assert result is not None
    assert result.get("source") == "text"
    assert result.get("status") != "invalid"
    assert result.get("status") in {"passed", "converged", "success", "review_enqueued"}


def test_apply_backtest_kwargs_overlays_cached_config() -> None:
    """Journey 3: cache-hit configs must still honor workstation mode knobs."""
    cfg = ReplicationConfig(
        id="c1",
        report_id="r1",
        factor_specs=[],
        backtest_params=BacktestParams(
            start_date=date(2018, 1, 1),
            end_date=date(2024, 12, 31),
            mode="factor",
        ),
        parser_version="1",
        extraction_model_id="m",
        created_at=datetime.now(UTC),
    )
    updated = apply_backtest_kwargs(
        cfg,
        {
            "mode": "strategy",
            "direction": "long_flat",
            "selection_rule": "top_n",
            "top_n": 3,
        },
    )
    assert updated.backtest_params.mode == "strategy"
    assert updated.backtest_params.direction == "long_flat"
    assert updated.backtest_params.top_n == 3
    assert cfg.backtest_params.mode == "factor"
    token_a = backtest_params_token(cfg.backtest_params)
    token_b = backtest_params_token(updated.backtest_params)
    assert token_a != token_b


def test_backtester_empty_ic_is_finite(tmp_path: Path) -> None:
    """Empty cross-section IC must stay finite so the health gate can still pass."""
    from reproagent.reproducer.backtester import StrategyBacktester

    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(15)]
    fv = pl.DataFrame(
        [{"date": d, "asset": "AAA", "factor_value": float(i)} for i, d in enumerate(days)]
    )
    px = pl.DataFrame(
        [
            {"trade_date": d, "ts_code": "AAA", "close": 10.0 + float(i)}
            for i, d in enumerate(days)
        ]
    )
    fdef = FactorDefinition(
        id="one-asset",
        spec_id="s",
        name="one",
        name_cn="单资产",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    params = BacktestParams(start_date=days[0], end_date=days[-1], num_groups=5)
    result = StrategyBacktester(_settings(tmp_path)).run(fv, params, fdef, data=px)
    assert math.isfinite(result.ic_mean)
    assert math.isfinite(result.ic_ir)
    assert result.ic_mean == 0.0


def test_strategy_long_flat_does_not_short(tmp_path: Path) -> None:
    """Journey 3: long_flat + top_bottom_n must not short the bottom names."""
    from reproagent.reproducer.backtester import StrategyBacktester

    assets = ["a", "b", "c", "d", "e", "f"]
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(12)]
    fv_rows = []
    px_rows = []
    for i, d in enumerate(days):
        for j, a in enumerate(assets):
            fv_rows.append({"date": d, "asset": a, "factor_value": float(j)})
            px_rows.append(
                {"trade_date": d, "ts_code": a, "close": 10.0 + i + 0.2 * j}
            )
    fv = pl.DataFrame(fv_rows)
    px = pl.DataFrame(px_rows)
    fdef = FactorDefinition(
        id="ls-vs-flat",
        spec_id="s",
        name="rank",
        name_cn="排序",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    settings = _settings(tmp_path)
    bt = StrategyBacktester(settings)
    shared = dict(
        start_date=days[0],
        end_date=days[-1],
        mode="strategy",
        strategy_mode="time_series",
        selection_rule="top_bottom_n",
        top_n=2,
        bottom_n=2,
    )
    ls = bt.run(
        fv,
        BacktestParams(**shared, direction="long_short"),
        fdef.model_copy(update={"id": "ls"}),
        data=px,
    )
    flat = bt.run(
        fv,
        BacktestParams(**shared, direction="long_flat"),
        fdef.model_copy(update={"id": "flat"}),
        data=px,
    )
    assert math.isfinite(flat.long_short_annual_return)
    assert math.isfinite(ls.long_short_annual_return)
    assert flat.long_short_annual_return != ls.long_short_annual_return


def test_strategy_threshold_without_bounds_errors(tmp_path: Path) -> None:
    from reproagent.reproducer.backtester import StrategyBacktester

    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(8)]
    fv = pl.DataFrame(
        [{"date": d, "asset": "AAA", "factor_value": 1.0} for d in days]
    )
    px = pl.DataFrame(
        [{"trade_date": d, "ts_code": "AAA", "close": 10.0 + i} for i, d in enumerate(days)]
    )
    fdef = FactorDefinition(
        id="th-miss",
        spec_id="s",
        name="th",
        name_cn="阈值",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    params = BacktestParams(
        start_date=days[0],
        end_date=days[-1],
        mode="strategy",
        selection_rule="threshold",
    )
    with pytest.raises(ValueError, match="long_threshold"):
        StrategyBacktester(_settings(tmp_path)).run(fv, params, fdef, data=px)


def test_strategy_max_weight_scales_returns(tmp_path: Path) -> None:
    from reproagent.reproducer.backtester import StrategyBacktester

    assets = ["a", "b", "c", "d"]
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(12)]
    fv_rows = []
    px_rows = []
    for i, d in enumerate(days):
        for j, a in enumerate(assets):
            fv_rows.append({"date": d, "asset": a, "factor_value": float(j)})
            px_rows.append(
                {"trade_date": d, "ts_code": a, "close": 10.0 + i + 0.3 * j}
            )
    fv = pl.DataFrame(fv_rows)
    px = pl.DataFrame(px_rows)
    settings = _settings(tmp_path)
    bt = StrategyBacktester(settings)
    shared = dict(
        start_date=days[0],
        end_date=days[-1],
        mode="strategy",
        selection_rule="top_n",
        top_n=1,
        direction="long_only",
    )
    fdef = FactorDefinition(
        id="cap-w",
        spec_id="s",
        name="cap",
        name_cn="上限",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    full = bt.run(
        fv,
        BacktestParams(**shared),
        fdef.model_copy(update={"id": "full-w"}),
        data=px,
    )
    capped = bt.run(
        fv,
        BacktestParams(**shared, max_weight_per_position=0.1),
        fdef.model_copy(update={"id": "capped-w"}),
        data=px,
    )
    assert full.long_short_annual_return != 0
    ratio = capped.long_short_annual_return / full.long_short_annual_return
    assert 0.05 < ratio < 0.2


def test_strategy_min_holding_days_lowers_turnover(tmp_path: Path) -> None:
    from reproagent.reproducer.backtester import StrategyBacktester

    assets = ["a", "b"]
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(16)]
    fv_rows = []
    px_rows = []
    for i, d in enumerate(days):
        # Flip the leader every day so unconstrained turnover is high.
        fv_rows.append({"date": d, "asset": "a", "factor_value": float(i % 2)})
        fv_rows.append({"date": d, "asset": "b", "factor_value": float((i + 1) % 2)})
        for j, a in enumerate(assets):
            px_rows.append(
                {"trade_date": d, "ts_code": a, "close": 10.0 + i + 0.2 * j}
            )
    fv = pl.DataFrame(fv_rows)
    px = pl.DataFrame(px_rows)
    settings = _settings(tmp_path)
    bt = StrategyBacktester(settings)
    shared = dict(
        start_date=days[0],
        end_date=days[-1],
        mode="strategy",
        selection_rule="top_n",
        top_n=1,
        direction="long_only",
    )
    fdef = FactorDefinition(
        id="hold",
        spec_id="s",
        name="hold",
        name_cn="持有",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    daily = bt.run(
        fv,
        BacktestParams(**shared, min_holding_days=1),
        fdef.model_copy(update={"id": "hold-1"}),
        data=px,
    )
    sticky = bt.run(
        fv,
        BacktestParams(**shared, min_holding_days=5),
        fdef.model_copy(update={"id": "hold-5"}),
        data=px,
    )
    assert sticky.turnover < daily.turnover


def test_strategy_exit_threshold_changes_result(tmp_path: Path) -> None:
    from reproagent.reproducer.backtester import StrategyBacktester

    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(12)]
    fv_rows = []
    px_rows = []
    for i, d in enumerate(days):
        # Enter on first two days (fv>=1); then sit at 0.7 (below entry, above exit=0.5).
        fv = 2.0 if i < 2 else 0.7
        fv_rows.append({"date": d, "asset": "a", "factor_value": fv})
        fv_rows.append({"date": d, "asset": "b", "factor_value": 0.0})
        px_rows.append({"trade_date": d, "ts_code": "a", "close": 10.0 + i})
        px_rows.append({"trade_date": d, "ts_code": "b", "close": 10.0})
    fv = pl.DataFrame(fv_rows)
    px = pl.DataFrame(px_rows)
    settings = _settings(tmp_path)
    bt = StrategyBacktester(settings)
    shared = dict(
        start_date=days[0],
        end_date=days[-1],
        mode="strategy",
        selection_rule="threshold",
        long_threshold=1.0,
        direction="long_flat",
        min_holding_days=2,
    )
    fdef = FactorDefinition(
        id="exit",
        spec_id="s",
        name="exit",
        name_cn="退出",
        style="other",
        formula="close",
        input_fields=["close"],
        universe="local_panel",
        rebalance_frequency="daily",
    )
    held = bt.run(
        fv,
        BacktestParams(**shared),
        fdef.model_copy(update={"id": "exit-none"}),
        data=px,
    )
    exited = bt.run(
        fv,
        BacktestParams(**shared, exit_threshold=0.5),
        fdef.model_copy(update={"id": "exit-th"}),
        data=px,
    )
    assert held.long_short_annual_return != exited.long_short_annual_return


def test_backtest_bundle_unique_paths_and_mean_factor(tmp_path: Path) -> None:
    """MCP/eval bundle must not overwrite artifacts and must return mean_factor."""
    from reproagent.reproducer.backtest_bundle import build_backtest_bundle

    settings = _settings(tmp_path)
    a = build_backtest_bundle("close", universe="local_panel", settings=settings)
    b = build_backtest_bundle("close", universe="local_panel", settings=settings)
    assert a["factor_values_path"] != b["factor_values_path"]
    assert Path(a["factor_values_path"]).exists()
    assert Path(b["equity_curve_path"]).exists()
    fv = pl.read_parquet(a["factor_values_path"])
    expected = float(fv["factor_value"].drop_nulls().mean() or 0.0)
    assert a["mean_factor"] == pytest.approx(expected)


def test_library_grade_impl_runs_local_expression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reproagent.mcp_server import library_grade_impl
    from reproagent.settings import get_settings

    monkeypatch.setenv("DATA_SOURCE", "local")
    monkeypatch.setenv("LOCAL_DATA_PATH", str(Path("tests/fixtures/test_data").resolve()))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "grade-data"))
    get_settings.cache_clear()
    try:
        out = library_grade_impl("close", None)
    finally:
        get_settings.cache_clear()
    assert out["scorer"] == "library_grade"
    assert "score" in out
    assert out.get("backtest_id")
    assert "error" not in out


def test_tui_metrics_for_gauge_skips_non_finite() -> None:
    from reproagent.tui.screens.reproduction import metrics_for_gauge

    out = metrics_for_gauge(
        {
            "factors": [
                {
                    "metrics": {
                        "ic_mean": 0.1,
                        "sharpe_ratio": float("nan"),
                        "note": "x",
                    }
                }
            ]
        }
    )
    assert out["ic_mean"] == pytest.approx(0.1)
    assert "sharpe_ratio" not in out
    assert "note" not in out
    assert metrics_for_gauge(None) == {}


def test_tui_library_screen_uses_factor_tree() -> None:
    import inspect

    from reproagent.tui.screens.library_browser import FactorLibraryScreen
    from reproagent.tui.widgets.factor_tree import FactorTree

    tree = FactorTree("所有因子", id="factor-tree")
    assert tree.id == "factor-tree"
    src = inspect.getsource(FactorLibraryScreen.compose)
    assert "FactorTree" in src


def test_tui_reproduce_screen_uses_log_panel() -> None:
    import inspect

    from reproagent.tui.screens.reproduction import ReportReproductionScreen
    from reproagent.tui.widgets.log_panel import LogPanel

    panel = LogPanel()
    panel.write_line("hello")
    src = inspect.getsource(ReportReproductionScreen.compose)
    assert "LogPanel" in src


def test_tui_subtitle_lists_bindings() -> None:
    from reproagent.tui.app import ReproAgentApp, tui_subtitle
    from reproagent.tui.commands import COMMANDS

    text = tui_subtitle()
    assert text == ReproAgentApp.SUB_TITLE
    assert "r 复现研报" in text
    assert "l 打开因子库" in text
    assert "v 人工复核" in text
    assert {c.id for c in COMMANDS} >= {"reproduce", "library", "review"}


def test_tui_reproduce_rejects_directory(tmp_path: Path) -> None:
    from reproagent.tui.screens.reproduction import reproduce_input_error

    folder = tmp_path / "dir"
    folder.mkdir()
    assert "不是文件" in (reproduce_input_error(str(folder)) or "")
    assert reproduce_input_error(str(tmp_path / "missing.pdf"))
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    assert reproduce_input_error(str(pdf)) is None
    assert reproduce_input_error("  ") == "请输入 PDF 路径。"


def test_tui_review_banner_does_not_invent_reflection() -> None:
    from reproagent.tui.screens.reproduction import review_enqueued_banner

    text = review_enqueued_banner({"status": "review_enqueued", "reflection_status": "confidence_gate"})
    assert "confidence_gate" in text
    assert "Reflection" not in text
    assert "偏差过大" not in text
    fallback = review_enqueued_banner({"status": "review_enqueued"})
    assert "人工复核" in fallback


def test_tui_parse_banner_is_honest_offline() -> None:
    from pydantic import SecretStr

    from reproagent.settings import Settings
    from reproagent.tui.screens.reproduction import parse_stage_banner

    offline = Settings(allow_mock_llm=True, llm_api_key=SecretStr(""))
    banner = parse_stage_banner(offline)
    assert "mock" in banner.lower()
    assert "DeepSeek" not in banner
    assert "PaddleOCR" not in banner


def test_json_dumps_rejects_nan() -> None:
    import json

    from reproagent.utils.jsonutil import dumps, json_ready

    payload = {"ic_mean": float("nan"), "ok": 1.5, "nested": [float("inf"), 2]}
    ready = json_ready(payload)
    assert ready["ic_mean"] is None
    assert ready["nested"][0] is None
    text = dumps(payload)
    parsed = json.loads(text)
    assert parsed["ic_mean"] is None
    assert parsed["ok"] == 1.5
    assert parsed["nested"][0] is None


def test_tui_library_tree_caps_and_filters() -> None:
    from datetime import UTC, datetime

    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.tui.screens.library_browser import select_library_entries_for_view

    now = datetime.now(UTC)
    entries = []
    for i in range(12):
        style = "momentum" if i % 2 == 0 else "value"
        name = f"{style}_{i}"
        entries.append(
            FactorLibraryEntry(
                id=f"e-{i}",
                factor=FactorDefinition(
                    id=f"f-{i}",
                    spec_id=f"s-{i}",
                    name=name,
                    name_cn=name,
                    style=style,  # type: ignore[arg-type]
                    formula="close" if style == "value" else "close/Ref(close,5)-1",
                    input_fields=["close"],
                    universe="all",
                    rebalance_frequency="monthly",
                ),
                report_id="r",
                config_id="c",
                backtest_result_id="b",
                deviation_passed=True,
                version="1.0.0",
                dedup_hash=f"{i:016x}deadbeef",
                tags=[],
                created_at=now,
            )
        )
    shown, total = select_library_entries_for_view(entries, limit=5)
    assert total == 12
    assert len(shown) == 5
    mom, mom_total = select_library_entries_for_view(entries, query="momentum", limit=20)
    assert mom_total == 6
    assert all("momentum" in e.factor.name for e in mom)


def test_tui_library_markdown_includes_metrics() -> None:
    from datetime import UTC, datetime

    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.tui.screens.library_browser import format_library_entry_md

    entry = FactorLibraryEntry(
        id="e-tui",
        factor=FactorDefinition(
            id="f",
            spec_id="s",
            name="tui_mom",
            name_cn="TUI动量",
            style="momentum",
            formula="close",
            input_fields=["close"],
            universe="all",
            rebalance_frequency="monthly",
        ),
        report_id="r",
        config_id="c",
        backtest_result_id="b",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="deadbeefcafebabe",
        tags=["tui"],
        created_at=datetime.now(UTC),
        metrics={"ic": 0.11, "sharpe": 0.9},
    )
    md = format_library_entry_md(entry)
    assert "### 回测指标" in md
    assert "0.11" in md
    assert "tui_mom" in md


def test_anti_overfitting_placebo_from_fixture_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reproagent.mcp_server import run_anti_overfitting_from_equity
    from reproagent.reproducer.backtest_bundle import build_backtest_bundle
    from reproagent.settings import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATA_SOURCE", "local")
    monkeypatch.setenv("LOCAL_DATA_PATH", str(Path("tests/fixtures/test_data").resolve()))
    get_settings.cache_clear()
    try:
        bundle = build_backtest_bundle("close")
        anti = run_anti_overfitting_from_equity(bundle.get("equity_curve_path"))
        assert anti.get("dsr") is not None
        assert anti.get("placebo_pvalue") is not None
        assert 0.0 <= float(anti["placebo_pvalue"]) <= 1.0
    finally:
        get_settings.cache_clear()


def test_placebo_pvalue_reads_p_value_field() -> None:
    from reproagent.mcp_server import placebo_pvalue_from_result
    from reproagent.reproducer.anti_overfitting import PlaceboResult

    result = PlaceboResult(
        true_ic=0.1,
        placebo_mean=0.0,
        placebo_std=0.05,
        p_value=0.02,
        n_shuffles=50,
        significant=True,
    )
    assert placebo_pvalue_from_result(result) == pytest.approx(0.02)
    assert placebo_pvalue_from_result({"p_value": 0.4}) == pytest.approx(0.4)
    assert placebo_pvalue_from_result({"pvalue": 0.3}) == pytest.approx(0.3)
    assert placebo_pvalue_from_result(None) is None


def test_library_grade_from_library_entry_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """score_factor(backtest_id=library_id) must use stored metrics, not a dummy C."""
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.mcp_server import library_grade_impl
    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.library import FactorLibraryEntry
    from reproagent.models.report import ResearchReport
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.settings import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        engine = get_engine(settings.db_path)
        init_db(engine)
        repo = Repository(engine)
        paths = AppPaths.from_settings(settings)
        paths.ensure_layout()
        manager = FactorLibraryManager(repository=repo, paths=paths)
        report = ResearchReport(
            id="rep-grade",
            file_path=tmp_path / "a.pdf",
            file_hash="hg",
            page_count=1,
            validation_status="valid",
            ingested_at=datetime.now(UTC),
        )
        repo.save_report(report)
        entry = FactorLibraryEntry(
            id="lib-grade-1",
            factor=FactorDefinition(
                id="id-grade",
                spec_id="spec-grade",
                name="grade_mom",
                name_cn="grade_mom",
                style="momentum",
                formula="close/Ref(close,5)-1",
                input_fields=["close"],
                universe="all",
                rebalance_frequency="monthly",
            ),
            report_id=report.id,
            config_id="c",
            backtest_result_id="bt-grade-xyz",
            deviation_passed=True,
            version="1.0.0",
            dedup_hash="dh-grade",
            tags=[],
            created_at=datetime.now(UTC),
            metrics={"ic": 0.1, "sharpe": 1.0, "max_drawdown": 0.05},
        )
        manager.register(entry)
        by_id = library_grade_impl(None, "lib-grade-1")
        by_bt = library_grade_impl(None, "bt-grade-xyz")
    finally:
        get_settings.cache_clear()
    assert by_id.get("scorer") == "library_grade"
    assert "note" not in by_id
    assert by_id["grade"] in {"A", "B", "C", "D"}
    assert by_id["score"] != 0
    assert by_id["components"]["ic_mean"] == pytest.approx(0.1)
    assert by_bt["library_id"] == "lib-grade-1"
    assert by_bt["score"] == by_id["score"]


def test_library_grade_unknown_id_is_error_not_dummy_c() -> None:
    from reproagent.mcp_server import library_grade_impl

    out = library_grade_impl(None, "no-such-id")
    assert out["grade"] == "D"
    assert "not found" in out.get("error", "")
    assert "note" not in out


def test_library_grade_impl_does_not_need_fastmcp() -> None:
    from reproagent.mcp_server import library_grade_impl

    out = library_grade_impl(None, None)
    assert out["grade"] == "D"
    assert "error" in out
    assert out["scorer"] == "library_grade"


def test_empty_openai_api_key_alias_disables_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """README offline command exports OPENAI_API_KEY=; that must beat .env LLM_API_KEY."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-be-used")
    settings = Settings(_env_file=None)
    assert settings.llm_api_key.get_secret_value() == ""


def test_minimal_gt_omits_unclaimed_return_metrics() -> None:
    """Advertised `benchmark --run minimal` must not treat placeholder 0 as GT."""
    from reproagent.benchmark.runner import _spec_from_gt_factor, load_ground_truth

    gt = load_ground_truth("minimal")
    spec = _spec_from_gt_factor(gt["factors"][0])
    reported = spec.reported_metrics
    assert reported is not None
    assert reported.ic_mean == pytest.approx(-0.3333333333333333)
    assert reported.ic_ir == pytest.approx(-0.3461093276215864)
    assert reported.long_short_return is None
    assert reported.sharpe_ratio is None
    assert reported.max_drawdown is None


def test_benchmark_minimal_passes_on_local_fixture(tmp_path: Path) -> None:
    """README smoke path: ground-truth IC/ICIR match fixture backtest."""
    from reproagent.benchmark.runner import run_benchmark

    result = run_benchmark("minimal", _settings(tmp_path))
    assert result["status"] == "passed", result
    assert result["summary"]["passed"] == 1
    assert result["summary"]["failed"] == 0
    assert result["factors"][0]["deviation_passed"] is True
    reported = result["factors"][0]["reported_metrics"]
    assert reported["long_short_return"] is None
    assert reported["sharpe_ratio"] is None


def test_benchmark_cb_factor_investing_passes_on_local_fixture(tmp_path: Path) -> None:
    """README `benchmark --run cb-factor-investing` is a fixture-aligned smoke path."""
    from reproagent.benchmark.runner import run_benchmark

    result = run_benchmark("cb-factor-investing", _settings(tmp_path))
    assert result["status"] == "passed", result
    assert result["summary"]["failed"] == 0
    assert result["summary"]["errors"] == 0
    assert result["summary"]["passed"] == result["summary"]["total"] >= 1


def test_benchmark_report_includes_last_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        out = settings.data_dir / "benchmark" / "minimal"
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "summary": {"total": 1, "passed": 1, "failed": 0, "errors": 0},
                }
            ),
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(app, ["benchmark", "--report"])
        assert result.exit_code == 0, result.output
        assert "## Last run results" in result.output
        assert "minimal" in result.output
        assert "status=passed" in result.output
        assert "passed=1" in result.output
    finally:
        get_settings.cache_clear()


def test_web_jobs_list_returns_queued_jobs(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path)
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )
    empty = json.loads(app.handle("GET", "/api/jobs").body)
    assert empty["count"] == 0
    md = tmp_path / "snip.md"
    md.write_text("动量 close / Ref(close, 5) - 1\n", encoding="utf-8")
    created = app.handle(
        "POST",
        "/api/reproduce",
        body=json.dumps({"path": str(md)}).encode(),
    )
    assert created.status == 202
    listed = json.loads(app.handle("GET", "/api/jobs").body)
    assert listed["count"] == 1
    assert listed["items"][0]["job_id"] == json.loads(created.body)["job_id"]


def test_web_health_includes_version(tmp_path: Path) -> None:
    from reproagent import __version__
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path)
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )
    resp = app.handle("GET", "/api/health")
    assert resp.status == 200
    payload = json.loads(resp.body)
    assert payload["ok"] is True
    assert payload["version"] == __version__


def test_web_favicon_is_empty_204(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path)
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )
    resp = app.handle("GET", "/favicon.ico")
    assert resp.status == 204
    assert resp.body == b""


def test_web_prod_500_omits_traceback(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path).model_copy(update={"app_env": "prod"})
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )

    class _Boom:
        def list(self, *args: object, **kwargs: object) -> list:
            raise RuntimeError("boom-secret")

    app.manager = _Boom()  # type: ignore[assignment]
    resp = app.handle("GET", "/api/library")
    assert resp.status == 500
    payload = json.loads(resp.body)
    assert "boom-secret" in payload["error"]
    assert "trace" not in payload
    assert "Traceback" not in resp.body.decode()


def test_web_reproduce_rejects_directory(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path)
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )
    folder = tmp_path / "not-a-report"
    folder.mkdir()
    resp = app.handle(
        "POST",
        "/api/reproduce",
        body=json.dumps({"path": str(folder)}).encode(),
    )
    assert resp.status == 400
    assert "not a file" in json.loads(resp.body)["error"]


def test_web_invalid_json_is_400_not_500(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path)
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )
    resp = app.handle("POST", "/api/reproduce", body=b"not-json")
    assert resp.status == 400
    payload = json.loads(resp.body)
    assert "invalid JSON" in payload["error"]
    assert "trace" not in payload
    resp2 = app.handle("POST", "/api/review/x", body=b"null")
    assert resp2.status == 400
    assert "decision" in json.loads(resp2.body)["error"] or "JSON" in json.loads(resp2.body)["error"]


def test_web_rejects_invalid_backtest_kwargs(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.paths import AppPaths
    from reproagent.persistence.repository import Repository
    from reproagent.web.app import WebApp

    settings = _settings(tmp_path)
    engine = get_engine(settings.db_path)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    app = WebApp(
        settings=settings,
        repository=repo,
        manager=FactorLibraryManager(repository=repo, paths=paths),
    )
    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    body = json.dumps(
        {"path": str(pdf), "backtest_kwargs": {"mode": "not-a-real-mode"}}
    ).encode()
    resp = app.handle("POST", "/api/reproduce", body=body)
    assert resp.status == 400
    payload = json.loads(resp.body)
    assert "invalid backtest_kwargs" in payload["error"]
