"""入库门、衰减检查、仪表盘质量字段。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from reproagent.library.admission import gate_register
from reproagent.library.dashboard import library_dashboard_payload, normalize_dashboard_factor
from reproagent.library.decay_monitor import run_library_decay_check
from reproagent.library.manager import FactorLibraryManager
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.library import FactorLibraryEntry
from reproagent.models.report import ResearchReport
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository


def _entry(fid: str, name: str, report_id: str, formula: str = "close") -> FactorLibraryEntry:
    return FactorLibraryEntry(
        id=fid,
        factor=FactorDefinition(
            id=fid,
            spec_id=fid,
            name=name,
            name_cn=name,
            style="other",
            formula=formula,
            input_fields=["close"],
            universe="all",
            rebalance_frequency="daily",
        ),
        report_id=report_id,
        config_id="c",
        backtest_result_id="b",
        deviation_passed=True,
        version="1.0.0",
        dedup_hash="",
        created_at=datetime.now(UTC),
        metrics={"ic": 0.1},
    )


def _manager(tmp_path: Path) -> FactorLibraryManager:
    engine = get_engine(tmp_path / "m.db")
    init_db(engine)
    repo = Repository(engine)
    repo.save_report(
        ResearchReport(
            id="rep",
            file_path=tmp_path / "a.pdf",
            file_hash="h",
            page_count=1,
            validation_status="valid",
            ingested_at=datetime.now(UTC),
        )
    )
    return FactorLibraryManager(repository=repo, paths=AppPaths(data_dir=tmp_path))


def test_register_flags_redundant_factor(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(12)]
    fv = pl.DataFrame(
        [
            {"date": d, "asset": a, "factor_value": float(j + i)}
            for i, d in enumerate(days)
            for j, a in enumerate(["x", "y", "z"])
        ]
    )
    folder = tmp_path / "backtest" / "old"
    folder.mkdir(parents=True)
    fv.write_parquet(folder / "factor_values.parquet")
    pl.DataFrame({"date": days[:3], "ls_return": [0.01, -0.01, 0.0]}).write_parquet(
        folder / "equity_curve.parquet"
    )
    first = _entry("old", "alpha", "rep", "close")
    first = first.model_copy(update={"backtest_result_id": "old"})
    manager.register(first, check_redundancy=False)

    saved, decision = gate_register(
        manager, _entry("new", "copy", "rep", "close+1"), factor_values=fv
    )
    assert decision.accepted is False
    assert decision.redundant is True
    assert saved.status == "review"
    assert "redundant" in saved.tags


def test_register_invokes_anti_overfitting_on_backtest(tmp_path: Path) -> None:
    from types import SimpleNamespace

    manager = _manager(tmp_path)
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(30)]
    eq = pl.DataFrame(
        {
            "date": days,
            "ls_return": [0.02 if i % 2 == 0 else -0.001 for i in range(30)],
        }
    )
    folder = tmp_path / "bt"
    folder.mkdir()
    eq.write_parquet(folder / "equity_curve.parquet")
    bt = SimpleNamespace(equity_curve_path=folder / "equity_curve.parquet")
    saved, decision = gate_register(manager, _entry("n1", "n", "rep"), backtest=bt)
    assert "anti_overfitting" in (saved.metrics or {})
    assert decision.anti.get("n_obs") == 30 or decision.anti.get("pbo") is not None


def test_decay_cli_entry_flips_status() -> None:
    decaying = run_library_decay_check({"d": (0.10, 0.06)})
    assert decaying.factors[0].status == "decaying"
    deprecated = run_library_decay_check({"x": (0.10, 0.04)})
    assert deprecated.factors[0].status == "deprecated"
    stable = run_library_decay_check({"s": (0.10, 0.09)})
    assert stable.factors[0].status == "stable"


def test_dashboard_payload_has_quality_keys() -> None:
    entry = _entry("d1", "dash", "rep")
    payload = library_dashboard_payload(entry)
    stats = payload["stats"]
    for key in ("fitness", "self_correlation", "coverage", "production_correlation"):
        assert key in stats
    norm = normalize_dashboard_factor(payload)
    for key in ("fitness", "self_correlation", "coverage", "production_correlation"):
        assert key in norm["stats"]


def test_dashboard_html_renders_quality_kpis(tmp_path: Path) -> None:
    from reproagent.library.dashboard import generate_html_dashboard

    entry = _entry("d1", "dash", "rep")
    payload = library_dashboard_payload(entry)
    out = generate_html_dashboard([payload], tmp_path / "dash.html")
    html = out.read_text(encoding="utf-8")
    assert "function statsOf" in html
    assert "fmtQual" in html
    assert "Fitness" in html
    assert "自相关" in html
    assert "覆盖" in html
    assert "生产相关" in html
    for key in ("fitness", "self_correlation", "coverage", "production_correlation"):
        assert key in html
        assert f"s.{key}" in html or f"fmtQual(s.{key}" in html
    dumped = html[html.find("const FACTORS = ") : html.find("function num")]
    assert "fitness" in dumped
    assert "production_correlation" in dumped


def test_decay_from_ic_parquet_tail_flips_status(tmp_path: Path) -> None:
    import pytest

    from reproagent.library.decay_monitor import (
        current_ic_from_artifacts,
        pairs_from_library_entries,
        run_library_decay_check,
    )

    manager = _manager(tmp_path)
    entry = _entry("decay1", "mom_decay", "rep")
    entry = entry.model_copy(
        update={"metrics": {"ic": 0.10}, "backtest_result_id": "decay1"}
    )
    manager.register(entry, check_redundancy=False)

    folder = tmp_path / "backtest" / "decay1"
    folder.mkdir(parents=True)
    dates = [date(2023, 1, 2) + timedelta(days=i) for i in range(30)]
    # Early history still 0.10; recent tail is 0.04 → 60% drop → deprecated.
    ics = [0.10] * 10 + [0.04] * 20
    pl.DataFrame({"date": dates, "ic": ics}).write_parquet(folder / "ic.parquet")
    pl.DataFrame({"date": dates[:2], "ls_return": [0.01, 0.0]}).write_parquet(
        folder / "equity_curve.parquet"
    )

    current = current_ic_from_artifacts(tmp_path, manager.get("decay1"), tail=20)
    assert current == pytest.approx(0.04)
    pairs = pairs_from_library_entries(manager.list(), data_dir=tmp_path, tail=20)
    assert pairs["decay1"][0] == pytest.approx(0.10)
    assert pairs["decay1"][1] == pytest.approx(0.04)
    assert pairs["decay1"][1] != pairs["decay1"][0]
    report = run_library_decay_check(pairs)
    assert report.factors[0].status == "deprecated"

    # 0.0 recent IC is a real reading (must not fall back to orig via falsy-or).
    pl.DataFrame({"date": dates, "ic": [0.0] * 30}).write_parquet(folder / "ic.parquet")
    zero = current_ic_from_artifacts(tmp_path, manager.get("decay1"), tail=20)
    assert zero == pytest.approx(0.0)
    pairs0 = pairs_from_library_entries(manager.list(), data_dir=tmp_path, tail=20)
    assert pairs0["decay1"][1] == pytest.approx(0.0)
    assert run_library_decay_check(pairs0).factors[0].status == "deprecated"

    # 40% drop → decaying
    pl.DataFrame({"date": dates, "ic": [0.10] * 10 + [0.06] * 20}).write_parquet(
        folder / "ic.parquet"
    )
    pairs_d = pairs_from_library_entries(manager.list(), data_dir=tmp_path, tail=20)
    assert pairs_d["decay1"][1] == pytest.approx(0.06)
    assert run_library_decay_check(pairs_d).factors[0].status == "decaying"
