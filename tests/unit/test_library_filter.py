"""因子库 style/broker/tags 过滤。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
