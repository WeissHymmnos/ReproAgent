"""人工复核队列入队 / 出队。"""

from __future__ import annotations

from typing import Literal

from reproagent.models.report import ResearchReport


def enqueue_manual_review(report: ResearchReport, reason: str) -> str:
    """将报告加入人工复核队列，返回 queue_entry_id。"""
    raise NotImplementedError("ingestion.review_queue.enqueue_manual_review")


def dequeue_manual_review() -> tuple[str, ResearchReport, str] | None:
    """取出队首项：(entry_id, report, reason)。"""
    raise NotImplementedError("ingestion.review_queue.dequeue_manual_review")


def confirm_manual_review(
    entry_id: str,
    decision: Literal["approve", "reject"],
) -> None:
    """人工确认：approve → RegisterReady；reject → 终止。"""
    raise NotImplementedError("ingestion.review_queue.confirm_manual_review")
