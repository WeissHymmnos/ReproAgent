"""人工复核队列入队 / 出队。"""

from __future__ import annotations

from typing import Literal

from reproagent.models.report import ResearchReport
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.repository import Repository
from reproagent.settings import get_settings


def review_capability_kind(reason: str) -> str | None:
    """Bucket a review reason as a system-capability failure, or None if a human should review."""
    r = (reason or "").strip()
    if not r:
        return None
    if r.startswith("Strict mode"):
        return None
    if r.startswith("Confidence gate"):
        # Only empty formula needs a person; low confidence / WARN tags are
        # extractor quality and the pipeline already soft-continues those.
        if "empty_formula" in r:
            return None
        return "extraction_confidence"
    if r.startswith("No factors extracted"):
        return "extraction"
    if r.startswith("Reflection failed"):
        return "reflection"
    lowered = r.lower()
    if r.startswith("PDF validation") or lowered.startswith("validation_failed"):
        return "validation"
    if r.startswith("Factor ") and " failed" in r:
        if any(tok in lowered for tok in ("ricequant", "rqdata", "rqdatac", "tushare")):
            return "data_source"
        if "universe" in lowered:
            return "data_source"
        if any(
            tok in lowered
            for tok in ("errno 2", "filenotfound", "no such file", "is a directory")
        ):
            return "wiki_path"
        if any(
            tok in lowered
            for tok in ("evaluat", "unparseable", "could not parse", "syntax")
        ):
            return "formula_engine"
        return "factor_runtime"
    return None


def should_enqueue_human_review(reason: str) -> bool:
    """True only for reasons that actually need a person, not a system-capability failure."""
    return review_capability_kind(reason) is None


def _default_repo() -> Repository:
    settings = get_settings()
    engine = get_engine(settings.db_path)
    init_db(engine)
    return Repository(engine)


def enqueue_manual_review(
    report: ResearchReport,
    reason: str,
    repo: Repository | None = None,
    *,
    human_only: bool = True,
) -> str | None:
    """将报告加入人工复核队列，返回 queue_entry_id。

    若报告尚未持久化则先 save_report（upsert 语义）。
    系统能力失败默认不入队（human_only=True）。
    """
    repo = repo or _default_repo()
    repo.save_report(report)
    return repo.enqueue_review(report.id, reason, human_only=human_only)


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
    info = repo.get_review(entry_id)
    status = "approved" if decision == "approve" else "rejected"
    repo.update_review_status(entry_id, status)
    _record_human_review_memory(repo, decision, info)


def _record_human_review_memory(
    repo: Repository,
    decision: Literal["approve", "reject"],
    info: dict | None,
) -> None:
    """Persist HUMAN GOOD/BAD so review decisions are not discarded."""
    try:
        from reproagent.memory.store import MemoryStore
        from reproagent.memory.writer import MemoryWriter
        from reproagent.settings import get_settings

        payload = (info or {}).get("payload") if isinstance(info, dict) else {}
        factor_name = None
        if isinstance(payload, dict):
            factor_name = payload.get("factor_name") or payload.get("name")
        reason = str((info or {}).get("reason") or "")
        if not factor_name and reason.startswith("Factor ") and " failed" in reason:
            factor_name = reason[len("Factor ") :].split(" failed", 1)[0].strip() or None
        writer = MemoryWriter(MemoryStore(repo), get_settings())
        writer.write_human_decision(
            report_id=(info or {}).get("report_id") if info else None,
            factor_name=str(factor_name) if factor_name else None,
            decision=decision,
            reason=str((info or {}).get("reason") or ""),
        )
    except Exception:  # noqa: BLE001
        return
