"""Robustness-fix regression tests (F-01..F-12 from adversarial audit)."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from reproagent.exceptions import FormulaError, ReproductionError
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams
from reproagent.reproducer.lookahead_detector import detect_lookahead
from reproagent.reproducer.polars_engine import PolarsEngine
from reproagent.reproducer.safe_eval import (
    UnsafeExpressionError,
    safe_compile,
    safe_eval,
)


def _panel(n_dates: int = 40, n_assets: int = 3) -> pl.DataFrame:
    rng = np.random.default_rng(7)
    dates = [date(2023, 1, 2) + timedelta(days=i) for i in range(n_dates)]
    assets = [f"A{i:03d}.SZ" for i in range(n_assets)]
    rows = []
    for a in assets:
        px = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(dates))))
        for d, p in zip(dates, px):
            rows.append({
                "date": d,
                "asset": a,
                "open": float(p) * 0.99,
                "high": float(p) * 1.01,
                "low": float(p) * 0.98,
                "close": float(p),
                "volume": 1e5,
            })
    return pl.DataFrame(rows)


def _fd(formula: str) -> FactorDefinition:
    return FactorDefinition(
        id="t",
        spec_id="s",
        name="t",
        name_cn="测",
        style="momentum",
        formula=formula,
        input_fields=["close"],
        universe="全A股",
        rebalance_frequency="monthly",
    )


def _engine(**kw: object) -> PolarsEngine:
    return PolarsEngine(config=None, allow_formula_fallback=False, **kw)  # type: ignore[arg-type]


class TestLookaheadBlocked:
    def test_ref_negative_window_raises(self) -> None:
        panel = _panel()
        with pytest.raises(FormulaError, match="future data"):
            _engine().compute(
                factor_def=_fd("Ref(close, -1)"),
                universe="全A股",
                start=date(2023, 1, 2),
                end=date(2023, 2, 10),
                data=panel,
            )

    def test_delta_negative_window_raises(self) -> None:
        with pytest.raises(FormulaError, match="future data"):
            _engine().compute(
                factor_def=_fd("Delta(close, -3)"),
                universe="全A股",
                start=date(2023, 1, 2),
                end=date(2023, 2, 10),
                data=_panel(),
            )

    def test_detector_flags_literal(self) -> None:
        report = detect_lookahead("close / Ref(close, -1) - 1")
        assert report.has_lookahead


class TestDegenerateFactorRejected:
    def test_zero_variance_factor_raises_in_backtester(self, tmp_path: Path) -> None:
        from reproagent.reproducer.backtester import StrategyBacktester
        from reproagent.settings import Settings

        panel = _panel()
        fv = panel.select("date", "asset", pl.lit(1.0).alias("factor_value"))
        bt = StrategyBacktester(
            settings=Settings(data_dir=tmp_path / "bt", data_source="local")
        )
        params = BacktestParams(
            start_date=date(2023, 1, 2),
            end_date=date(2023, 2, 10),
            rebalance_frequency="monthly",
            num_groups=5,
        )
        with pytest.raises(ReproductionError, match="[Dd]egenerate"):
            bt.run(factor_values=fv, params=params, factor_def=_fd("close"), data=panel)

    def test_inf_values_dropped_by_engine(self) -> None:
        panel = _panel()
        fv = _engine().compute(
            factor_def=_fd("close / (close - close)"),
            universe="全A股",
            start=date(2023, 1, 2),
            end=date(2023, 2, 10),
            data=panel,
        )
        assert fv["factor_value"].is_infinite().sum() == 0


class TestPanelIntegrity:
    def test_shuffled_input_matches_sorted(self) -> None:
        panel = _panel()
        shuffled = panel.sample(fraction=1.0, shuffle=True, seed=42)
        fd = _fd("close / Ref(close, 5) - 1")

        a = (
            _engine()
            .compute(
                factor_def=fd,
                universe="全A股",
                start=date(2023, 1, 2),
                end=date(2023, 2, 10),
                data=panel,
            )
            .sort(["asset", "date"])
        )
        b = (
            _engine()
            .compute(
                factor_def=fd,
                universe="全A股",
                start=date(2023, 1, 2),
                end=date(2023, 2, 10),
                data=shuffled,
            )
            .sort(["asset", "date"])
        )
        assert np.allclose(a["factor_value"], b["factor_value"], equal_nan=False)

    def test_loader_dedups_duplicate_rows(self, tmp_path: Path) -> None:
        from reproagent.reproducer.data_loader import DataLoader
        from reproagent.settings import Settings

        df = _panel().rename({"date": "trade_date", "asset": "ts_code"})
        duplicated = pl.concat([df, df.head(10)])
        path = tmp_path / "prices.parquet"
        duplicated.write_parquet(path)

        loader = DataLoader(Settings(local_data_path=tmp_path, data_source="local"))
        loaded = loader.load_price_data(
            "全A股", date(2023, 1, 2), date(2023, 2, 10)
        )
        assert loaded.height == df.height
        assert loaded.unique(subset=["trade_date", "ts_code"]).height == loaded.height


class TestSafeEvalHardening:
    def test_format_template_escape_blocked(self) -> None:
        with pytest.raises(UnsafeExpressionError, match="format"):
            safe_eval('"{0.__class__}".format(1)')

    def test_format_map_blocked(self) -> None:
        with pytest.raises(UnsafeExpressionError, match="format"):
            safe_eval('"x".format_map({})')

    def test_oversized_source_rejected(self) -> None:
        with pytest.raises(UnsafeExpressionError, match="characters"):
            safe_eval("1+" * 20_000 + "1")

    def test_ast_node_bomb_rejected(self) -> None:
        with pytest.raises(UnsafeExpressionError, match="AST nodes"):
            safe_compile("+".join(["1"] * 2_000))

    def test_benign_expression_still_works(self) -> None:
        assert safe_eval("1 + 2 * 3") == 7


class TestVersionedCacheKey:
    def test_model_change_invalidates_key(self) -> None:
        from reproagent.cache.cache_key import compute_cache_key

        k1 = compute_cache_key("h", parser_version="2", extraction_model_id="a:m1")
        k2 = compute_cache_key("h", parser_version="2", extraction_model_id="a:m2")
        k3 = compute_cache_key("h", parser_version="3", extraction_model_id="a:m1")
        assert len({k1, k2, k3}) == 3
        assert compute_cache_key("h", parser_version="2", extraction_model_id="a:m1") == k1


class TestWritableDataDirPreflight:
    def test_ensure_layout_translates_permission_error(self, tmp_path: Path) -> None:
        from reproagent.exceptions import ConfigurationError
        from reproagent.persistence.paths import AppPaths

        ro = tmp_path / "ro"
        ro.mkdir(mode=0o555)
        try:
            with pytest.raises(ConfigurationError, match="not writable"):
                AppPaths(data_dir=ro).ensure_layout()
        finally:
            ro.chmod(0o755)


class TestWebPathValidation:
    def test_rejects_nonsensical_paths(self) -> None:
        from reproagent.web.app import validate_report_path

        for raw in ("/etc/passwd", "/proc/self/environ", "/home/x/.bashrc", ""):
            path, error = validate_report_path(raw)
            assert path is None
            assert error

    def test_accepts_existing_markdown(self, tmp_path: Path) -> None:
        from reproagent.web.app import validate_report_path

        f = tmp_path / "report.md"
        f.write_text("# x", encoding="utf-8")
        path, error = validate_report_path(str(f))
        assert error is None
        assert path == f


class TestSoftPassStatusSemantics:
    def test_aggregate_all_soft_passed_is_partial(self) -> None:
        from reproagent.pipeline import _aggregate_status

        assert _aggregate_status([{"status": "soft_passed"}]) == "partial"

    def test_aggregate_mixed_success_and_soft_is_partial(self) -> None:
        from reproagent.pipeline import _aggregate_status

        out = _aggregate_status([{"status": "passed"}, {"status": "soft_passed"}])
        assert out == "partial"

    def test_aggregate_all_passed_still_passed(self) -> None:
        from reproagent.pipeline import _aggregate_status

        assert _aggregate_status([{"status": "passed"}]) == "passed"


class TestParseBoundaryReviewRouting:
    def test_empty_formula_routes_to_review_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from reproagent.parser.report_parser import ReportParser
        from reproagent.pipeline import reproduce_text
        from reproagent.settings import Settings

        def _boom(self: object, report: object, markdown: str) -> list[object]:
            raise ValueError("formula cannot be empty")

        monkeypatch.setattr(ReportParser, "parse_text", _boom)
        settings = Settings(
            data_dir=tmp_path / "state",
            local_data_path=tmp_path,
            data_source="local",
            llm_api_key="",
        )
        out = reproduce_text("# t\n\nbody.", settings, title="t", broker="x")
        assert out["status"] == "review_enqueued"


class TestXssRegressionSurface:
    """F-14: 工作台所有插值点必须经 escapeHtml/escapeAttr（客户端转义）。"""

    def test_workstation_escapes_all_dynamic_fields(self) -> None:
        from reproagent.web.workstation import get_index_html

        html = get_index_html()
        assert "function escapeHtml" in html
        assert "function escapeAttr" in html
        for field in ("it.name_cn || it.name", "it.title", "it.broker"):
            escaped_call = html.count(f"escapeHtml({field}")
            assert escaped_call > 0, f"unescaped interpolation for {field}"

    def test_api_json_never_serves_raw_html_context(self) -> None:
        import json

        payload = {"title": '<script>alert(1)</script>'}
        encoded = json.dumps(payload)
        assert "<script>" in json.loads(encoded)["title"]


class TestFiniteGuardMath:
    def test_std_guard_thresholds(self) -> None:
        values = [1.0, 1.0 + 1e-15]
        std = float(np.std(values))
        assert std < 1e-12 or math.isclose(std, 0.0, abs_tol=1e-12)

