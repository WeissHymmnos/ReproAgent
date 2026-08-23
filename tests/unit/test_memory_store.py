"""Phase 0：研究记忆 schema 与 MemoryStore 往返。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from reproagent.memory.store import MemoryStore
from reproagent.models.memory import (
    EligibilityDecision,
    FeedbackKind,
    FeedbackQuery,
    FeedbackRecord,
    FeedbackSource,
    MechanismFamily,
    ReportKnowledgeAtom,
    ResearchArchetype,
)
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository


@pytest.fixture()
def repo(tmp_path: Path) -> Repository:
    db = tmp_path / "test.db"
    engine = get_engine(db)
    init_db(engine)
    return Repository(engine)


@pytest.fixture()
def store(repo: Repository) -> MemoryStore:
    return MemoryStore(repo)


def test_paths_memory_layout(tmp_path: Path) -> None:
    paths = AppPaths(data_dir=tmp_path)
    paths.ensure_layout()
    assert paths.memory_dir.is_dir()
    assert paths.memory_feedback_good_dir.is_dir()
    assert paths.memory_feedback_bad_dir.is_dir()
    assert paths.memory_knowledge_dir.is_dir()


def test_knowledge_atom_roundtrip(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    atom = ReportKnowledgeAtom(
        id=uuid4().hex,
        report_id="rep-1",
        chunk_text="20-day momentum using close",
        source_pages=[1, 2],
        a_decision=EligibilityDecision.KEEP,
        a_reason="expressible from daily close",
        mechanism_family=MechanismFamily.MOMENTUM,
        research_path="rank short-horizon continuation",
        created_at=now,
    )
    store.save_knowledge(atom)
    listed = store.list_knowledge("rep-1")
    assert len(listed) == 1
    assert listed[0].a_decision == EligibilityDecision.KEEP
    assert listed[0].mechanism_family == MechanismFamily.MOMENTUM


def test_archetype_roundtrip(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    arch = ResearchArchetype(
        id="C-mom-init",
        family=MechanismFamily.MOMENTUM,
        role="initiation momentum",
        report_grounded_paths=["short formation continuation"],
        source_report_ids=["rep-1"],
        notes="from RMA C-layer",
        created_at=now,
        updated_at=now,
    )
    store.save_archetype(arch)
    got = store.get_archetype("C-mom-init")
    assert got is not None
    assert got.role == "initiation momentum"
    assert got.family == MechanismFamily.MOMENTUM


def test_feedback_query_excludes_mock_by_default(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    bad_real = FeedbackRecord(
        id=uuid4().hex,
        kind=FeedbackKind.BAD,
        report_id="rep-1",
        factor_name="mock_momentum",
        mechanism_family=MechanismFamily.MOMENTUM,
        failure_type="reflection_exhausted",
        root_cause="data_mismatch",
        avoid_rule="do not only multiply formula by 1.0",
        repair_hint="align lookback or reported metrics",
        metrics_summary={"ic_mean_delta": -0.05},
        source=FeedbackSource.REAL,
        created_at=now,
    )
    bad_mock = FeedbackRecord(
        id=uuid4().hex,
        kind=FeedbackKind.BAD,
        factor_name="mock_momentum",
        mechanism_family=MechanismFamily.MOMENTUM,
        failure_type="reflection_exhausted",
        source=FeedbackSource.MOCK,
        created_at=now,
    )
    store.save_feedback(bad_real)
    store.save_feedback(bad_mock)

    default = store.query_feedback(
        FeedbackQuery(kind=FeedbackKind.BAD, mechanism_family=MechanismFamily.MOMENTUM)
    )
    assert len(default) == 1
    assert default[0].source == FeedbackSource.REAL

    with_mock = store.query_feedback(
        FeedbackQuery(
            kind=FeedbackKind.BAD,
            mechanism_family=MechanismFamily.MOMENTUM,
            include_mock=True,
            limit=10,
        )
    )
    assert len(with_mock) == 2


def test_enqueue_review_with_payload(repo: Repository) -> None:
    # need a report row for FK — use raw enqueue without FK enforcement if SQLite off
    # Repository does not require report exists for enqueue in practice if FK off;
    # create_all may enable FK. Save minimal via engine if needed.
    from sqlmodel import Session

    from reproagent.persistence.tables import ReportTable

    with Session(repo.engine) as session:
        session.add(
            ReportTable(
                id="rep-x",
                file_hash="h",
                file_path="/tmp/x.pdf",
                title=None,
                author=None,
                broker=None,
                report_date=None,
                page_count=1,
                validation_status="valid",
                validation_errors_json="[]",
                ingested_at=datetime.now(UTC).isoformat(),
            )
        )
        session.commit()

    entry_id = repo.enqueue_review(
        "rep-x",
        "Reflection failed for mock_momentum: exhausted",
        payload={"failure_type": "reflection_exhausted", "factor_name": "mock_momentum"},
        human_only=False,
    )
    assert entry_id
    item = repo.dequeue_review()
    assert item is not None
    assert item[0] == entry_id
