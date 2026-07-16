"""人工复核队列入队 / 出队。"""

from __future__ import annotations

from typing import Literal

from reproagent.models.report import ResearchReport
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.repository import Repository
from reproagent.settings import get_settings


def _default_repo() -> Repository:
    settings = get_settings()
    engine = get_engine(settings.db_path)
    init_db(engine)
    return Repository(engine)


def enqueue_manual_review(
    report: ResearchReport,
    reason: str,
    repo: Repository | None = None,
) -> str:
    """将报告加入人工复核队列，返回 queue_entry_id。

    若报告尚未持久化则先 save_report（upsert 语义）。
    """
    repo = repo or _default_repo()
    repo.save_report(report)
    return repo.enqueue_review(report.id, reason)


def dequeue_manual_review(
    repo: Repository | None = None,
) -> tuple[str, ResearchReport, str] | None:
    """取出队首项：(entry_id, report, reason)。无待审项返回 None。"""
    repo = repo or _default_repo()
    entry = repo.dequeue_review()
    if entry is None:
        return None
    entry_id, report_id, reason = entry
    report = repo.get_report(report_id)
    if report is None:
        return None
    return (entry_id, report, reason)


def confirm_manual_review(
    entry_id: str,
    decision: Literal["approve", "reject"],
    repo: Repository | None = None,
) -> None:
    """人工确认：approve → 进入 RegisterReady；reject → 终止。"""
    repo = repo or _default_repo()
    status = "approved" if decision == "approve" else "rejected"
    repo.update_review_status(entry_id, status)