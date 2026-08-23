"""因子库 style/broker/tags 过滤。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from reproagent.library.manager import FactorLibraryManager
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.library import FactorLibraryEntry, LibraryFilter
from reproagent.models.report import ResearchReport
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository


def _factor(style: str, name: str = "f", formula: str = "close") -> FactorDefinition:
    return FactorDefinition(
        id=f"id-{name}",
        spec_id=f"spec-{name}",
        name=name,
        name_cn=name,
        style=style,  # type: ignore[arg-type]
        formula=formula,
        input_fields=["close"],
        universe="all",
        rebalance_frequency="monthly",
    )


def test_list_library_filter_style_and_broker(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths(data_dir=tmp_path / "data")
    paths.ensure_layout()
    manager = FactorLibraryManager(repository=repo, paths=paths)

    report = ResearchReport(
        id="rep1",
        file_path=tmp_path / "a.pdf",
        file_hash="h1",
        title="t",
        author=None,
        broker="HT",
        report_date=None,
        page_count=1,
        validation_status="valid",
        validation_errors=[],
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)

    now = datetime.now(UTC)
    # 名称含分类关键词，且 formula 不同以避免 dedup 合并
    cases = (
        ("value", "value_pe", "1/close"),
        ("momentum", "momentum_ret", "close/Ref(close,20)-1"),
    )
    for style, name, formula in cases:
        manager.register(
            FactorLibraryEntry(
                id=f"e-{name}",
                factor=_factor(style, name, formula=formula),
                report_id=report.id,
                config_id="c1",
                backtest_result_id="b1",
                deviation_passed=True,
                version="0.1.0",
                dedup_hash="",
                tags=["alpha"],
                created_at=now,
            )
        )

    value_entries = manager.list(LibraryFilter(style="value"))
    assert len(value_entries) == 1
    assert value_entries[0].factor.style == "value"

    broker_entries = manager.list(LibraryFilter(broker="HT"))
    assert len(broker_entries) == 2

    tagged = manager.list(LibraryFilter(tags=["alpha"]))
    assert len(tagged) == 2

    empty = manager.list(LibraryFilter(style="quality"))
    assert empty == []

    by_name = manager.list(query="momentum")
    assert [e.factor.name for e in by_name] == ["momentum_ret"]
    by_formula = manager.list(query="1/close")
    assert [e.factor.name for e in by_formula] == ["value_pe"]
    capped = manager.list(limit=1)
    assert len(capped) == 1
    assert len(manager.list()) == 2


def test_library_metrics_roundtrip_and_dashboard(tmp_path: Path) -> None:

    from reproagent.library.dashboard import (
        generate_html_dashboard,
        library_dashboard_payload,
    )
    from reproagent.models.factor_def import FactorDefinition
    from reproagent.models.replication import BacktestParams
    from reproagent.reproducer.backtester import StrategyBacktester
    from reproagent.reproducer.metrics import metrics_from_backtest
    from reproagent.settings import Settings

    engine = get_engine(tmp_path / "m.db")
    init_db(engine)
    repo = Repository(engine)
    report = ResearchReport(
        id="rep-m",
        file_path=tmp_path / "a.pdf",
        file_hash="hm",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)

    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(12)]
    fv = pl.DataFrame(
        [
            {"date": d, "asset": a, "factor_value": float(j + i)}
            for i, d in enumerate(days)
            for j, a in enumerate(["x", "y", "z"])
        ]
    )
    px = pl.DataFrame(
        [
            {"trade_date": d, "ts_code": a, "close": 10.0 + i + 0.1 * j}
            for i, d in enumerate(days)
            for j, a in enumerate(["x", "y", "z"])
        ]
    )
    settings = Settings(data_dir=tmp_path / "data")
    result = StrategyBacktester(settings).run(
        fv,
        BacktestParams(start_date=days[0], end_date=days[-1], num_groups=3),
        FactorDefinition(
            id="m-bt",
            spec_id="s",
            name="m_bt",
            name_cn="指标",
            style="other",
            formula="close",
            input_fields=["close"],
            universe="local_panel",
            rebalance_frequency="daily",
        ),
        data=px,
    )
    stored = metrics_from_backtest(result)
    assert "ic" in stored
    assert stored["ic_series"]  # equity curve has daily ls_return
    assert len(stored["ic_series"]) == len(stored["excess_cum"])

    entry = FactorLibraryEntry(
        id="e-m",
        factor=_factor("momentum", "m_bt", formula="close/Ref(close,5)-1"),
        report_id=report.id,
        config_id="c",
        backtest_result_id=result.id,
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="h",
        tags=[],
        created_at=datetime.now(UTC),
        metrics=stored,
    )
    repo.save_library_entry(entry)
    loaded = repo.get_library_entry("e-m")
    assert loaded is not None
    assert loaded.metrics["ic"] == stored["ic"]
    payload = library_dashboard_payload(loaded)
    assert payload["stats"]["ic"] == pytest.approx(stored["ic"])
    assert payload["stats"]["ann_return"] == pytest.approx(stored["ann_return"] * 100.0)
    assert payload["ic_series"] == stored["ic_series"]
    html = generate_html_dashboard([payload], tmp_path / "dash-m.html").read_text(
        encoding="utf-8"
    )
    assert "m_bt" in html
    assert "function statsOf" in html


def test_register_preserves_existing_metrics(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "keep.db")
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths(data_dir=tmp_path / "data")
    paths.ensure_layout()
    manager = FactorLibraryManager(repository=repo, paths=paths)
    report = ResearchReport(
        id="rep-keep",
        file_path=tmp_path / "a.pdf",
        file_hash="hk",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)
    first = FactorLibraryEntry(
        id="e-keep",
        factor=_factor("momentum", "keep_mom", formula="close/Ref(close,5)-1"),
        report_id=report.id,
        config_id="c",
        backtest_result_id="bt",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="",
        tags=[],
        created_at=datetime.now(UTC),
        metrics={"ic": 0.42, "ic_series": [0.1, 0.2]},
    )
    manager.register(first)
    blank = FactorLibraryEntry(
        id="e-keep-2",
        factor=_factor("momentum", "keep_mom", formula="close/Ref(close,5)-1"),
        report_id=report.id,
        config_id="c2",
        backtest_result_id="bt2",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="",
        tags=[],
        created_at=datetime.now(UTC),
        metrics={},
    )
    saved = manager.register(blank)
    loaded = manager.get(saved.id)
    assert loaded is not None
    assert loaded.metrics["ic"] == pytest.approx(0.42)
    assert loaded.metrics["ic_series"] == [0.1, 0.2]


def test_backfill_metrics_from_artifact_dir(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "bf.db")
    init_db(engine)
    repo = Repository(engine)
    data = tmp_path / "data"
    paths = AppPaths(data_dir=data)
    paths.ensure_layout()
    manager = FactorLibraryManager(repository=repo, paths=paths)
    report = ResearchReport(
        id="rep-bf",
        file_path=tmp_path / "a.pdf",
        file_hash="hbf",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)
    entry = FactorLibraryEntry(
        id="e-bf",
        factor=_factor("momentum", "bf_mom", formula="Rank(close)"),
        report_id=report.id,
        config_id="c",
        backtest_result_id="bt-bf",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="",
        tags=[],
        created_at=datetime.now(UTC),
        metrics={},
    )
    manager.register(entry)
    art = data / "backtest" / "bf_mom"
    art.mkdir(parents=True)
    pl.DataFrame(
        {
            "date": [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4)],
            "ls_return": [0.01, -0.005, 0.02],
        }
    ).write_parquet(art / "equity_curve.parquet")
    pl.DataFrame({"date": [date(2023, 1, 2), date(2023, 1, 3)], "ic": [0.2, 0.4]}).write_parquet(
        art / "ic.parquet"
    )
    n = manager.backfill_metrics(data)
    assert n == 1
    loaded = manager.get(entry.id)
    assert loaded is not None
    assert loaded.metrics["ic"] == pytest.approx(0.3)
    assert loaded.metrics["ic_series"] == [0.01, -0.005, 0.02]
    assert manager.backfill_metrics(data) == 0


def test_find_backtest_artifact_dir_ignores_generic_factor_id(tmp_path: Path) -> None:
    """Shared extractor ids like factor_6 must not attach another factor's folder."""
    from types import SimpleNamespace

    from reproagent.reproducer.metrics import find_backtest_artifact_dir

    root = tmp_path / "backtest"
    stolen = root / "factor_6"
    stolen.mkdir(parents=True)
    pl.DataFrame(
        {"date": [date(2023, 1, 2)], "ls_return": [0.5], "ic": [0.9]}
    ).write_parquet(stolen / "equity_curve.parquet")
    pl.DataFrame({"date": [date(2023, 1, 2)], "ic": [0.9]}).write_parquet(
        stolen / "ic.parquet"
    )

    own = root / "earnings_surprise"
    own.mkdir(parents=True)
    pl.DataFrame(
        {"date": [date(2023, 1, 2), date(2023, 1, 3)], "ls_return": [0.01, 0.02]}
    ).write_parquet(own / "equity_curve.parquet")
    pl.DataFrame({"date": [date(2023, 1, 2), date(2023, 1, 3)], "ic": [0.1, 0.3]}).write_parquet(
        own / "ic.parquet"
    )

    entry = SimpleNamespace(
        id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        backtest_result_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        factor=SimpleNamespace(
            id="factor_6",
            name="EarningsSurprise",
            name_cn="盈利惊喜",
        ),
    )
    assert find_backtest_artifact_dir(tmp_path, entry) is None

    # Case-insensitive name match (historical dirs are often lowercased).
    cased = SimpleNamespace(
        id="cccccccccccccccccccccccccccccccc",
        backtest_result_id="none",
        factor=SimpleNamespace(id="factor_6", name="Earnings_Surprise", name_cn=""),
    )
    assert find_backtest_artifact_dir(tmp_path, cased) == own

    prefixed = root / "Momentum_5D-deadbeef12"
    prefixed.mkdir(parents=True)
    pl.DataFrame(
        {"date": [date(2023, 1, 2)], "ls_return": [0.03]}
    ).write_parquet(prefixed / "equity_curve.parquet")
    named = SimpleNamespace(
        id="dddddddddddddddddddddddddddddddd",
        backtest_result_id="none",
        factor=SimpleNamespace(id="factor_1", name="Momentum_5D", name_cn="动量"),
    )
    assert find_backtest_artifact_dir(tmp_path, named) == prefixed


def test_library_metrics_column_migrates(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE reports (id TEXT PRIMARY KEY, file_hash TEXT, file_path TEXT, "
        "title TEXT, author TEXT, broker TEXT, report_date TEXT, page_count INTEGER, "
        "validation_status TEXT, validation_errors_json TEXT, ingested_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE factor_library (id TEXT PRIMARY KEY, factor_json TEXT, "
        "report_id TEXT, config_id TEXT, backtest_result_id TEXT, "
        "deviation_passed INTEGER, status TEXT, version TEXT, dedup_hash TEXT, "
        "tags_json TEXT, created_at TEXT)"
    )
    conn.commit()
    conn.close()
    engine = get_engine(db)
    init_db(engine)
    repo = Repository(engine)
    report = ResearchReport(
        id="rep-legacy",
        file_path=tmp_path / "a.pdf",
        file_hash="hl",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)
    entry = FactorLibraryEntry(
        id="e-legacy",
        factor=_factor("value", "legacy_pe", formula="1/close"),
        report_id=report.id,
        config_id="c",
        backtest_result_id="bt",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="hl2",
        tags=[],
        created_at=datetime.now(UTC),
        metrics={"ic": 0.08},
    )
    repo.save_library_entry(entry)
    loaded = repo.get_library_entry("e-legacy")
    assert loaded is not None
    assert loaded.metrics["ic"] == pytest.approx(0.08)


def test_library_metrics_json_stores_nan_as_null(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "nan.db")
    init_db(engine)
    repo = Repository(engine)
    report = ResearchReport(
        id="rep-nan",
        file_path=tmp_path / "a.pdf",
        file_hash="hn",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)
    entry = FactorLibraryEntry(
        id="e-nan",
        factor=_factor("value", "nan_pe", formula="1/close"),
        report_id=report.id,
        config_id="c",
        backtest_result_id="bt",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="hnan",
        tags=[],
        created_at=datetime.now(UTC),
        metrics={"ic": float("nan"), "sharpe": float("inf")},
    )
    repo.save_library_entry(entry)
    loaded = repo.get_library_entry("e-nan")
    assert loaded is not None
    assert loaded.metrics["ic"] is None
    assert loaded.metrics["sharpe"] is None


def test_html_dashboard_normalizes_empty_stats(tmp_path: Path) -> None:
    from reproagent.library.dashboard import (
        generate_html_dashboard,
        normalize_dashboard_factor,
    )

    raw = {
        "name": "Bad<Name>",
        "ic_series": [0.1],
        "excess_cum": [],
        "stats": {},
    }
    norm = normalize_dashboard_factor(raw)
    assert norm["stats"]["ic"] == 0.0
    assert norm["stats"]["icir"] == 0.0
    assert len(norm["ic_series"]) == len(norm["excess_cum"]) == 1
    out = generate_html_dashboard([raw], tmp_path / "dash.html")
    html = out.read_text(encoding="utf-8")
    assert "function statsOf" in html
    assert 'typeof Chart !== "function"' in html
    dumped = html[html.find("const FACTORS = ") : html.find("function num")]
    assert '"ic": 0.0' in dumped or '"ic": 0' in dumped
    assert "Bad<Name>" in html  # JSON string, not raw HTML tag injection of stats crash


def test_library_cli_query_and_limit(tmp_path: Path, monkeypatch) -> None:
    """Librarian `library -q … --limit` must filter and cap printed rows."""
    from typer.testing import CliRunner

    from reproagent.cli import app
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
            id="rep-cli-lib",
            file_path=tmp_path / "a.pdf",
            file_hash="h-cli",
            page_count=1,
            validation_status="valid",
            ingested_at=datetime.now(UTC),
        )
        repo.save_report(report)
        now = datetime.now(UTC)
        for style, name, formula in (
            ("value", "value_pe", "1/close"),
            ("momentum", "momentum_ret", "close/Ref(close,20)-1"),
        ):
            manager.register(
                FactorLibraryEntry(
                    id=f"e-{name}",
                    factor=_factor(style, name, formula=formula),
                    report_id=report.id,
                    config_id="c1",
                    backtest_result_id="b1",
                    deviation_passed=True,
                    version="0.1.0",
                    dedup_hash="",
                    tags=["alpha"],
                    created_at=now,
                )
            )
        runner = CliRunner()
        result = runner.invoke(app, ["library", "--query", "momentum", "--limit", "10"])
        assert result.exit_code == 0, result.output
        assert "momentum_ret" in result.output
        assert "value_pe" not in result.output
        capped = runner.invoke(app, ["library", "--limit", "1"])
        assert capped.exit_code == 0, capped.output
        assert "showing first 1" in capped.output

        art = settings.data_dir / "backtest" / "momentum_ret"
        art.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            {"date": [date(2023, 1, 2), date(2023, 1, 3)], "ls_return": [0.01, 0.02]}
        ).write_parquet(art / "equity_curve.parquet")
        stale = settings.wiki_dir / "dashboard.html"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("STALE_DASHBOARD_NO_METRICS", encoding="utf-8")
        refreshed = runner.invoke(app, ["library", "--refresh-metrics", "--limit", "10"])
        assert refreshed.exit_code == 0, refreshed.output
        assert "refreshed metrics for" in refreshed.output
        assert stale.exists()
        html = stale.read_text(encoding="utf-8")
        assert "STALE_DASHBOARD_NO_METRICS" not in html
        assert "momentum_ret" in html
        assert "html dashboard ->" in refreshed.output
    finally:
        get_settings.cache_clear()


def test_search_factor_library_impl_caps_without_fastmcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reproagent.mcp_server import search_factor_library_impl
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
            id="rep-mcp-lib",
            file_path=tmp_path / "a.pdf",
            file_hash="h-mcp",
            page_count=1,
            validation_status="valid",
            ingested_at=datetime.now(UTC),
        )
        repo.save_report(report)
        now = datetime.now(UTC)
        for i in range(8):
            name = f"mom_{i}" if i < 5 else f"val_{i}"
            style = "momentum" if i < 5 else "value"
            manager.register(
                FactorLibraryEntry(
                    id=f"e-{name}",
                    factor=_factor(style, name, formula=f"close+{i}"),
                    report_id=report.id,
                    config_id="c1",
                    backtest_result_id="b1",
                    deviation_passed=True,
                    version="0.1.0",
                    dedup_hash="",
                    tags=[],
                    created_at=now,
                )
            )
        capped = search_factor_library_impl("", None, limit=3)
        assert len(capped) == 3
        mom = search_factor_library_impl("mom", None, limit=10)
        assert mom
        assert all("mom" in row["name"] for row in mom)
        styled = search_factor_library_impl("", "value", limit=10)
        assert styled
        assert all(row["style"] == "value" for row in styled)
    finally:
        get_settings.cache_clear()
