"""RMA / mock skip / review dedupe / feedback integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from reproagent.memory.rma import assess_eligibility, infer_mechanism_family
from reproagent.memory.store import MemoryStore
from reproagent.memory.writer import MemoryWriter
from reproagent.models.factor_spec import FactorInputField, ParsedFactorSpec
from reproagent.models.memory import (
    EligibilityDecision,
    FeedbackKind,
    FeedbackQuery,
    FeedbackSource,
    MechanismFamily,
)
from reproagent.models.report import ReportedMetrics
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.repository import Repository
from reproagent.persistence.tables import ReportTable
from reproagent.settings import Settings


def _spec(
    *,
    name: str = "mock_momentum",
    inputs: list[FactorInputField] | None = None,
    formula: str = "close / Ref(close, 20) - 1",
) -> ParsedFactorSpec:
    return ParsedFactorSpec(
        id=uuid4().hex,
        factor_name=name,
        factor_name_cn="动量",
        description="momentum test",
        formula=formula,
        input_fields=inputs
        or [
            FactorInputField(
                name="close",
                report_name="收盘价",
                data_type="price",
            )
        ],
        computation_steps=["ret"],
        extraction_confidence=0.5,
        reported_metrics=ReportedMetrics(ic_mean=0.05),
    )


def test_infer_family_momentum() -> None:
    assert infer_mechanism_family(_spec()) == MechanismFamily.MOMENTUM


def test_a_layer_drop_fundamental_on_local() -> None:
    settings = Settings(data_source="local")
    spec = _spec(
        name="value_pe",
        inputs=[
            FactorInputField(
                name="pe",
                report_name="市盈率",
                data_type="fundamental",
            )
        ],
        formula="1/pe",
    )
    decision, reason = assess_eligibility(spec, settings)
    assert decision == EligibilityDecision.DROP
    assert "fundamental" in reason.lower() or "local" in reason.lower()


def test_a_layer_keep_price_on_local() -> None:
    settings = Settings(data_source="local")
    decision, _ = assess_eligibility(_spec(), settings)
    assert decision == EligibilityDecision.KEEP


def test_review_dedupe(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "d.db")
    init_db(engine)
    repo = Repository(engine)
    with __import__("sqlmodel").Session(engine) as session:
        session.add(
            ReportTable(
                id="r1",
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

    id1 = repo.enqueue_review(
        "r1",
        "Reflection failed for mock_momentum: exhausted",
        payload={"reason_type": "reflection_exhausted", "factor_name": "mock_momentum"},
        human_only=False,
    )
    id2 = repo.enqueue_review(
        "r1",
        "Reflection failed for mock_momentum: exhausted",
        payload={"reason_type": "reflection_exhausted", "factor_name": "mock_momentum"},
        human_only=False,
    )
    assert id1 == id2


def test_memory_writer_good_bad(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "m.db")
    init_db(engine)
    repo = Repository(engine)
    settings = Settings(data_source="local", data_dir=tmp_path)
    writer = MemoryWriter(MemoryStore(repo), settings)
    spec = _spec()
    summaries = writer.absorb_specs([spec], report_id="r1")
    assert summaries[0]["a_decision"] == "KEEP"
    assert summaries[0]["mechanism_family"] == "momentum"

    writer.write_bad(
        report_id="r1",
        spec=spec,
        factor_name=spec.factor_name,
        failure_type="reflection_skipped_mock",
        root_cause="data_mismatch",
        source=FeedbackSource.MOCK,
    )
    writer.write_good(
        report_id="r1",
        spec=spec,
        factor_id="fid",
        source=FeedbackSource.REAL,
    )
    # default excludes mock
    bads = MemoryStore(repo).query_feedback(
        FeedbackQuery(kind=FeedbackKind.BAD, include_mock=False)
    )
    assert bads == []
    bads_m = MemoryStore(repo).query_feedback(
        FeedbackQuery(kind=FeedbackKind.BAD, include_mock=True)
    )
    assert len(bads_m) == 1
    goods = MemoryStore(repo).query_feedback(FeedbackQuery(kind=FeedbackKind.GOOD))
    assert len(goods) == 1


def test_reproduce_mock_skips_reflection(tmp_path: Path) -> None:
    """离线 mock：偏差不过时 skip 反思并写 BAD，不刷多条队列。"""
    from reproagent.pipeline import reproduce_report

    data_dir = tmp_path / "ra"
    settings = Settings(
        app_env="dev",
        allow_mock_llm=True,
        llm_api_key="",  # type: ignore[arg-type]
        data_source="local",
        local_data_path=Path("tests/fixtures/test_data"),
        data_dir=data_dir,
        skip_mock_reflection=True,
        memory_enabled=True,
    )
    # SecretStr handling
    from pydantic import SecretStr

    settings = settings.model_copy(update={"llm_api_key": SecretStr("")})

    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    if not pdf.exists():
        pytest.skip("fixture pdf missing")

    out1 = reproduce_report(pdf, settings)
    assert out1 is not None
    assert out1["status"] in (
        "review_enqueued",
        "skipped_mock",
        "partial",
        "passed",
        "no_factors",
    )
    # mock fixture usually skip_mock reflection (no longer floods the review queue)
    if out1["status"] in {"review_enqueued", "skipped_mock"}:
        factors = out1.get("factors") or []
        assert factors
        assert factors[0].get("reflection_status") == "skipped_mock"
        assert out1.get("rma")

    # second run should not grow pending for same report+reason (dedupe)
    out2 = reproduce_report(pdf, settings)
    assert out2 is not None

    engine = get_engine(settings.db_path)
    init_db(engine)
    store = MemoryStore(Repository(engine))
    bads = store.query_feedback(
        FeedbackQuery(kind=FeedbackKind.BAD, include_mock=True, limit=50)
    )
    if out1["status"] in {"review_enqueued", "skipped_mock"}:
        assert any(b.failure_type == "reflection_skipped_mock" for b in bads)
        from sqlmodel import Session, select

        from reproagent.persistence.tables import ManualReviewQueueTable

        with Session(engine) as session:
            pending = session.exec(
                select(ManualReviewQueueTable).where(
                    ManualReviewQueueTable.status == "pending"
                )
            ).all()
        assert pending == []
    elif out1["status"] == "passed":
        assert not any(b.failure_type == "reflection_skipped_mock" for b in bads)
