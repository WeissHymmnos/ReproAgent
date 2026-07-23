"""人工复核队列 approve/reject 闭环。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
