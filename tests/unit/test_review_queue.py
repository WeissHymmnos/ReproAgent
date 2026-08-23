"""人工复核队列 approve/reject 闭环。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from reproagent.ingestion.review_queue import (
    confirm_manual_review,
    dequeue_manual_review,
    enqueue_manual_review,
)
from reproagent.models.report import ResearchReport
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.repository import Repository


def test_review_approve_reject_lifecycle(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "r.db")
    init_db(engine)
    repo = Repository(engine)

    report = ResearchReport(
        id="rep-1",
        file_path=tmp_path / "a.pdf",
        file_hash="hh",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    entry_id = enqueue_manual_review(report, "need eyes", repo=repo)
    item = dequeue_manual_review(repo=repo)
    assert item is not None
    assert item[0] == entry_id

    confirm_manual_review(entry_id, "approve", repo=repo)
    # 已处理，队首应为空（pending 无了）
    assert dequeue_manual_review(repo=repo) is None

    from reproagent.memory.store import MemoryStore
    from reproagent.models.memory import FeedbackKind, FeedbackQuery, FeedbackSource

    recs = MemoryStore(repo).query_feedback(
        FeedbackQuery(kind=FeedbackKind.GOOD, failure_type="human_approve", limit=10)
    )
    assert recs
    assert recs[0].source == FeedbackSource.HUMAN
    assert recs[0].report_id == "rep-1"
    assert "human_review" in recs[0].tags
    assert recs[0].principle == "need eyes"
    from reproagent.exceptions import PersistenceError

    with pytest.raises(PersistenceError, match="not pending"):
        confirm_manual_review(entry_id, "reject", repo=repo)


def test_review_memory_parses_factor_name_from_reason(tmp_path: Path) -> None:
    from reproagent.memory.store import MemoryStore
    from reproagent.models.memory import FeedbackKind, FeedbackQuery

    engine = get_engine(tmp_path / "r2.db")
    init_db(engine)
    repo = Repository(engine)
    report = ResearchReport(
        id="rep-fn",
        file_path=tmp_path / "b.pdf",
        file_hash="hh2",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    entry_id = enqueue_manual_review(
        report, "Factor mock_momentum failed: boom", repo=repo, human_only=False
    )
    confirm_manual_review(entry_id, "reject", repo=repo)
    recs = MemoryStore(repo).query_feedback(
        FeedbackQuery(kind=FeedbackKind.BAD, failure_type="human_reject", limit=10)
    )
    assert recs
    assert recs[0].factor_name == "mock_momentum"


def test_review_cli_missing_entry_is_clean_exit(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        result = runner.invoke(app, ["review", "--approve", "does-not-exist"])
        assert result.exit_code == 1
        assert "approve failed" in (result.output or "")
        assert "Traceback" not in (result.output or "")
        assert "PersistenceError" not in (result.output or "")
    finally:
        get_settings.cache_clear()


def test_web_review_missing_entry_is_404(tmp_path: Path) -> None:
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.paths import AppPaths
    from reproagent.settings import Settings
    from reproagent.web.app import WebApp

    settings = Settings(data_dir=tmp_path / "data", allow_mock_llm=True)
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
    resp = app.handle(
        "POST",
        "/api/review/does-not-exist",
        body=b'{"decision":"approve"}',
    )
    assert resp.status == 404
    import json

    payload = json.loads(resp.body)
    assert payload["error"] == "review entry not found"
    assert "trace" not in payload


def test_review_list_cli_caps_output(tmp_path: Path, monkeypatch) -> None:
    """Librarian `review --list` must not dump an unbounded pending queue."""
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
        for i in range(8):
            report = ResearchReport(
                id=f"rep-cap-{i}",
                file_path=tmp_path / f"a{i}.pdf",
                file_hash=f"h{i}",
                page_count=1,
                validation_status="valid",
                ingested_at=datetime.now(UTC),
            )
            enqueue_manual_review(report, f"reason-{i}", repo=repo)
        runner = CliRunner()
        result = runner.invoke(app, ["review", "--list", "--limit", "3"])
        assert result.exit_code == 0, result.output
        assert "review: 8 pending" in result.output
        assert "showing first 3 of 8" in result.output
        assert result.output.count("entry_id=") == 3

        stats = runner.invoke(app, ["review", "--stats"])
        assert stats.exit_code == 0, stats.output
        assert "review: 8 pending" in stats.output
        assert "reason-" in stats.output
        filtered = runner.invoke(app, ["review", "--list", "--reason", "reason-1"])
        assert filtered.exit_code == 0, filtered.output
        assert "reason-1" in filtered.output
        assert "reason-2" not in filtered.output

        peek = runner.invoke(app, ["review"])
        assert peek.exit_code == 0, peek.output
        assert "review: head" in peek.output
        assert "showing first" not in peek.output
        assert peek.output.count("entry_id=") == 1
    finally:
        get_settings.cache_clear()


def test_summarize_review_queue_includes_age_and_buckets() -> None:
    from types import SimpleNamespace

    from reproagent.cli import summarize_review_queue

    rows = [
        SimpleNamespace(reason="Reflection failed for A", created_at="2026-07-16"),
        SimpleNamespace(reason="Reflection failed for B", created_at="2026-08-01"),
        SimpleNamespace(reason="No factors extracted from text", created_at="2026-08-02"),
    ]
    text = summarize_review_queue(rows)
    assert "review: 3 pending" in text
    assert "oldest: 2026-07-16" in text
    assert "newest: 2026-08-02" in text
    assert "Reflection failed" in text
    assert "No factors extracted" in text
    assert summarize_review_queue([]) == "review: queue empty"


def test_review_reason_bucket_collapses_factor_names() -> None:
    from reproagent.cli import review_reason_bucket

    assert review_reason_bucket("Reflection failed for Momentum_1M") == "Reflection failed"
    assert review_reason_bucket("Factor UpwardVolatilityRatio failed: boom") == "Factor failed"
    assert review_reason_bucket("No factors extracted from text") == "No factors extracted"
    assert review_reason_bucket("Strict mode: proxy blocked") == "Strict mode"


def test_review_capability_kind_keeps_human_gates() -> None:
    from reproagent.ingestion.review_queue import (
        review_capability_kind,
        should_enqueue_human_review,
    )

    assert review_capability_kind("Confidence gate failed for X: empty_formula") is None
    assert (
        review_capability_kind(
            "Confidence gate failed for X: low_extraction_confidence=0.30<0.5"
        )
        == "extraction_confidence"
    )
    assert review_capability_kind("Strict mode: proxy formula rejected for X") is None
    assert review_capability_kind("need eyes on this extract") is None
    assert should_enqueue_human_review("Confidence gate failed for X: empty_formula")
    assert should_enqueue_human_review("Strict mode: universe fallback rejected")
    assert not should_enqueue_human_review(
        "Confidence gate failed for X: low_extraction_confidence=0.30<0.5"
    )

    assert review_capability_kind("No factors extracted from text") == "extraction"
    assert review_capability_kind("Reflection failed for A: exhausted") == "reflection"
    assert review_capability_kind("Reflection failed for A: skipped_mock") == "reflection"
    assert review_capability_kind("PDF validation failed") == "validation"
    assert review_capability_kind("validation_failed: junk") == "validation"
    assert (
        review_capability_kind("Factor mom failed: ricequant fetch timeout")
        == "data_source"
    )
    assert (
        review_capability_kind("Factor BE/ME failed: [Errno 2] No such file or directory")
        == "wiki_path"
    )
    assert (
        review_capability_kind("Factor mom failed: could not evaluate formula")
        == "formula_engine"
    )
    assert review_capability_kind("Factor mom failed: boom") == "factor_runtime"
    assert not should_enqueue_human_review("No factors extracted")
    assert not should_enqueue_human_review("Factor x failed: ricequant universe empty")


def test_capability_reasons_do_not_enqueue(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "cap.db")
    init_db(engine)
    repo = Repository(engine)
    report = ResearchReport(
        id="rep-cap",
        file_path=tmp_path / "c.pdf",
        file_hash="hc",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    assert enqueue_manual_review(report, "No factors extracted from text", repo=repo) is None
    assert enqueue_manual_review(report, "Reflection failed for A: exhausted", repo=repo) is None
    assert (
        enqueue_manual_review(
            report, "Factor A failed: ricequant fetch failed", repo=repo
        )
        is None
    )
    assert dequeue_manual_review(repo=repo) is None

    human = enqueue_manual_review(
        report, "Confidence gate failed for A: empty_formula", repo=repo
    )
    assert human
    item = dequeue_manual_review(repo=repo)
    assert item is not None
    assert item[0] == human


def test_dismiss_capability_reviews_keeps_human_items(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "dismiss.db")
    init_db(engine)
    repo = Repository(engine)
    report = ResearchReport(
        id="rep-d",
        file_path=tmp_path / "d.pdf",
        file_hash="hd",
        page_count=1,
        validation_status="valid",
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)
    cap_id = repo.enqueue_review(
        report.id, "No factors extracted", human_only=False
    )
    human_id = repo.enqueue_review(
        report.id, "Strict mode: proxy formula rejected for X"
    )
    other = repo.enqueue_review(
        report.id, "Factor Z failed: [Errno 2] No such file", human_only=False
    )
    assert cap_id and human_id and other

    result = repo.dismiss_capability_reviews()
    assert result["dismissed"] == 2
    assert result["kept"] == 1
    assert result["scanned"] == 3
    assert result["buckets"]["extraction"] == 1
    assert result["buckets"]["wiki_path"] == 1

    assert repo.get_review(cap_id)["status"] == "dismissed_capability"
    assert repo.get_review(other)["status"] == "dismissed_capability"
    assert repo.get_review(human_id)["status"] == "pending"
    item = dequeue_manual_review(repo=repo)
    assert item is not None
    assert item[0] == human_id


def test_review_cli_dismiss_capability(tmp_path: Path, monkeypatch) -> None:
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
        report = ResearchReport(
            id="rep-cli-d",
            file_path=tmp_path / "e.pdf",
            file_hash="he",
            page_count=1,
            validation_status="valid",
            ingested_at=datetime.now(UTC),
        )
        repo.save_report(report)
        repo.enqueue_review(
            report.id, "Reflection failed for A: exhausted", human_only=False
        )
        repo.enqueue_review(report.id, "Confidence gate failed for A: empty_formula")

        runner = CliRunner()
        result = runner.invoke(app, ["review", "--dismiss-capability"])
        assert result.exit_code == 0, result.output
        assert "dismissed_capability 1" in result.output
        assert "kept 1" in result.output
        assert "reflection" in result.output

        stats = runner.invoke(app, ["review", "--stats"])
        assert stats.exit_code == 0, stats.output
        assert "1 pending (1 human, 0 capability)" in stats.output
        assert "Confidence gate" in stats.output
        assert "Reflection failed" not in stats.output
    finally:
        get_settings.cache_clear()
