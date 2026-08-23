"""领域模型 CRUD 仓储。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as date_cls
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from reproagent.exceptions import PersistenceError
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.library import FactorLibraryEntry, LibraryFilter
from reproagent.models.memory import (
    FeedbackQuery,
    FeedbackRecord,
    FeedbackSource,
    ReportKnowledgeAtom,
    ResearchArchetype,
)
from reproagent.models.reflection import ReflectionState, ReflectionStep
from reproagent.models.report import ResearchReport
from reproagent.persistence.tables import (
    ArchetypeTable,
    FactorLibraryTable,
    FeedbackMemoryTable,
    ManualReviewQueueTable,
    ReflectionStateTable,
    ReportKnowledgeTable,
    ReportTable,
)
from reproagent.utils.jsonutil import dumps as json_dumps


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _to_report(row: ReportTable) -> ResearchReport:
    report_date: date_cls | None = (
        date_cls.fromisoformat(row.report_date) if row.report_date else None
    )
    ingested_at = datetime.fromisoformat(row.ingested_at)
    try:
        validation_errors = json.loads(row.validation_errors_json or "[]")
    except json.JSONDecodeError:
        validation_errors = []
    return ResearchReport(
        id=row.id,
        file_path=Path(row.file_path),
        file_hash=row.file_hash,
        title=row.title,
        author=row.author,
        broker=row.broker,
        report_date=report_date,
        page_count=row.page_count,
        validation_status=row.validation_status,  # type: ignore[arg-type]
        validation_errors=validation_errors,
        ingested_at=ingested_at,
    )


def _to_report_row(report: ResearchReport) -> ReportTable:
    return ReportTable(
        id=report.id,
        file_hash=report.file_hash,
        file_path=str(report.file_path),
        title=report.title,
        author=report.author,
        broker=report.broker,
        report_date=report.report_date.isoformat() if report.report_date else None,
        page_count=report.page_count,
        validation_status=report.validation_status,
        validation_errors_json=json.dumps(report.validation_errors, ensure_ascii=False),
        ingested_at=report.ingested_at.isoformat(),
    )


def _to_library_entry(row: FactorLibraryTable) -> FactorLibraryEntry:
    factor = FactorDefinition.model_validate_json(row.factor_json)
    tags = json.loads(row.tags_json or "[]")
    try:
        metrics = json.loads(getattr(row, "metrics_json", None) or "{}")
    except json.JSONDecodeError:
        metrics = {}
    if not isinstance(metrics, dict):
        metrics = {}
    return FactorLibraryEntry(
        id=row.id,
        factor=factor,
        report_id=row.report_id,
        config_id=row.config_id,
        backtest_result_id=row.backtest_result_id,
        deviation_passed=row.deviation_passed,
        status=row.status,  # type: ignore[arg-type]
        version=row.version,
        dedup_hash=row.dedup_hash,
        tags=tags,
        created_at=datetime.fromisoformat(row.created_at),
        metrics=metrics,
    )


def _to_library_row(entry: FactorLibraryEntry) -> FactorLibraryTable:
    return FactorLibraryTable(
        id=entry.id,
        factor_json=entry.factor.model_dump_json(),
        report_id=entry.report_id,
        config_id=entry.config_id,
        backtest_result_id=entry.backtest_result_id,
        deviation_passed=entry.deviation_passed,
        status=entry.status,
        version=entry.version,
        dedup_hash=entry.dedup_hash,
        tags_json=json.dumps(entry.tags, ensure_ascii=False),
        created_at=entry.created_at.isoformat(),
        metrics_json=json_dumps(entry.metrics or {}),
    )


def _to_reflection_state(row: ReflectionStateTable) -> ReflectionState:
    return ReflectionState.model_validate_json(row.state_json)


class Repository:
    """通用 CRUD：save/load 领域模型（映射 tables.py）。"""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # --- reports ---

    def save_report(self, report: ResearchReport) -> ResearchReport:
        with Session(self.engine) as session:
            row = _to_report_row(report)
            existing = session.get(ReportTable, report.id)
            if existing is None:
                session.add(row)
            else:
                for col in ReportTable.model_fields:
                    setattr(existing, col, getattr(row, col))
                session.add(existing)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"save_report failed: {exc}") from exc
        return report

    def get_report(self, report_id: str) -> ResearchReport | None:
        with Session(self.engine) as session:
            row = session.get(ReportTable, report_id)
            if row is None:
                return None
            return _to_report(row)

    def get_report_by_hash(self, file_hash: str) -> ResearchReport | None:
        with Session(self.engine) as session:
            stmt = select(ReportTable).where(ReportTable.file_hash == file_hash).limit(1)
            row = session.exec(stmt).first()
            if row is None:
                return None
            return _to_report(row)

    # --- library ---

    def save_library_entry(self, entry: FactorLibraryEntry) -> FactorLibraryEntry:
        with Session(self.engine) as session:
            row = _to_library_row(entry)
            existing = session.get(FactorLibraryTable, entry.id)
            if existing is None:
                session.add(row)
            else:
                for col in FactorLibraryTable.model_fields:
                    setattr(existing, col, getattr(row, col))
                session.add(existing)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"save_library_entry failed: {exc}") from exc
        return entry

    def get_library_entry(self, entry_id: str) -> FactorLibraryEntry | None:
        with Session(self.engine) as session:
            row = session.get(FactorLibraryTable, entry_id)
            if row is None:
                return None
            return _to_library_entry(row)

    def list_library_entries(
        self, filter_: LibraryFilter | None = None
    ) -> list[FactorLibraryEntry]:
        with Session(self.engine) as session:
            stmt = select(FactorLibraryTable)
            if filter_ is not None and filter_.status is not None:
                stmt = stmt.where(FactorLibraryTable.status == filter_.status)
            rows = session.exec(stmt).all()
            entries = [_to_library_entry(r) for r in rows]

        if filter_ is None:
            return entries

        if filter_.style is not None:
            entries = [e for e in entries if e.factor.style == filter_.style]

        if filter_.tags:
            wanted = set(filter_.tags)
            entries = [e for e in entries if wanted.issubset(set(e.tags))]

        if filter_.broker is not None:
            filtered: list[FactorLibraryEntry] = []
            for e in entries:
                report = self.get_report(e.report_id)
                if report is not None and report.broker == filter_.broker:
                    filtered.append(e)
            entries = filtered

        return entries

    def get_by_dedup_hash(self, dedup_hash: str) -> FactorLibraryEntry | None:
        with Session(self.engine) as session:
            stmt = (
                select(FactorLibraryTable)
                .where(FactorLibraryTable.dedup_hash == dedup_hash)
                .limit(1)
            )
            row = session.exec(stmt).first()
            if row is None:
                return None
            return _to_library_entry(row)

    # --- reflection ---

    def save_reflection_state(self, state: ReflectionState) -> ReflectionState:
        now = _now_iso()
        with Session(self.engine) as session:
            existing = session.get(ReflectionStateTable, state.id)
            state_json = state.model_dump_json()
            if existing is None:
                row = ReflectionStateTable(
                    id=state.id,
                    factor_id=state.factor_id,
                    report_id=state.report_id,
                    state_json=state_json,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                existing.factor_id = state.factor_id
                existing.report_id = state.report_id
                existing.state_json = state_json
                existing.updated_at = now
                session.add(existing)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"save_reflection_state failed: {exc}") from exc
        return state

    def get_reflection_state(self, state_id: str) -> ReflectionState | None:
        with Session(self.engine) as session:
            row = session.get(ReflectionStateTable, state_id)
            if row is None:
                return None
            return _to_reflection_state(row)

    def save_reflection_step(self, step: ReflectionStep) -> ReflectionStep:
        state = self.get_reflection_state(step.state_id)
        if state is None:
            raise PersistenceError(f"save_reflection_step: state {step.state_id} not found")
        existing_idx: int | None = None
        for idx, s in enumerate(state.steps):
            if s.id == step.id:
                existing_idx = idx
                break
        if existing_idx is None:
            state.steps.append(step)
        else:
            state.steps[existing_idx] = step
        state.updated_at = step.created_at
        self.save_reflection_state(state)
        return step

    # --- review queue ---

    def enqueue_review(
        self,
        report_id: str,
        reason: str,
        payload: dict[str, Any] | None = None,
        *,
        human_only: bool = True,
    ) -> str | None:
        if human_only:
            from reproagent.ingestion.review_queue import should_enqueue_human_review

            if not should_enqueue_human_review(reason):
                return None
        payload_json = json.dumps(payload or {}, default=str, ensure_ascii=False)
        with Session(self.engine) as session:
            existing = session.exec(
                select(ManualReviewQueueTable).where(
                    ManualReviewQueueTable.report_id == report_id,
                    ManualReviewQueueTable.reason == reason,
                    ManualReviewQueueTable.status == "pending",
                )
            ).first()
            if existing is not None:
                if payload is not None:
                    existing.payload_json = payload_json
                    session.add(existing)
                    session.commit()
                return existing.id
            entry_id = uuid4().hex
            row = ManualReviewQueueTable(
                id=entry_id,
                report_id=report_id,
                reason=reason,
                status="pending",
                created_at=_now_iso(),
                payload_json=payload_json,
            )
            session.add(row)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"enqueue_review failed: {exc}") from exc
        return entry_id

    def get_review(self, entry_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(ManualReviewQueueTable, entry_id)
            if row is None:
                return None
            try:
                payload = json.loads(row.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            return {
                "id": row.id,
                "report_id": row.report_id,
                "reason": row.reason,
                "status": row.status,
                "payload": payload,
            }

    def dequeue_review(self) -> tuple[str, str, str] | None:
        with Session(self.engine) as session:
            stmt = (
                select(ManualReviewQueueTable)
                .where(ManualReviewQueueTable.status == "pending")
                .order_by(ManualReviewQueueTable.created_at)
                .limit(1)
            )
            row = session.exec(stmt).first()
            if row is None:
                return None
            return (row.id, row.report_id, row.reason)

    def dismiss_capability_reviews(self) -> dict[str, Any]:
        """Mark pending system-capability failures as dismissed_capability.

        Does not approve or reject: those remain human decisions.
        """
        from reproagent.ingestion.review_queue import review_capability_kind

        dismissed = 0
        kept = 0
        buckets: dict[str, int] = {}
        with Session(self.engine) as session:
            rows = session.exec(
                select(ManualReviewQueueTable).where(
                    ManualReviewQueueTable.status == "pending"
                )
            ).all()
            for row in rows:
                kind = review_capability_kind(row.reason or "")
                if kind is None:
                    kept += 1
                    continue
                row.status = "dismissed_capability"
                session.add(row)
                dismissed += 1
                buckets[kind] = buckets.get(kind, 0) + 1
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(
                    f"dismiss_capability_reviews failed: {exc}"
                ) from exc
        return {
            "scanned": dismissed + kept,
            "dismissed": dismissed,
            "kept": kept,
            "buckets": buckets,
        }

    def update_review_status(self, entry_id: str, status: str) -> None:
        with Session(self.engine) as session:
            row = session.get(ManualReviewQueueTable, entry_id)
            if row is None:
                raise PersistenceError(f"update_review_status: entry {entry_id} not found")
            if row.status != "pending":
                raise PersistenceError(
                    f"update_review_status: entry {entry_id} is {row.status}, not pending"
                )
            row.status = status
            session.add(row)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"update_review_status failed: {exc}") from exc

    # --- research memory ---

    def save_knowledge_atom(self, atom: ReportKnowledgeAtom) -> ReportKnowledgeAtom:
        with Session(self.engine) as session:
            row = session.get(ReportKnowledgeTable, atom.id)
            payload = ReportKnowledgeTable(
                id=atom.id,
                report_id=atom.report_id,
                atom_json=atom.model_dump_json(),
                created_at=atom.created_at.isoformat(),
            )
            if row is None:
                session.add(payload)
            else:
                row.report_id = payload.report_id
                row.atom_json = payload.atom_json
                row.created_at = payload.created_at
                session.add(row)
            session.commit()
        return atom

    def list_knowledge_atoms(
        self, report_id: str | None = None, *, limit: int = 100
    ) -> list[ReportKnowledgeAtom]:
        with Session(self.engine) as session:
            stmt = select(ReportKnowledgeTable)
            if report_id:
                stmt = stmt.where(ReportKnowledgeTable.report_id == report_id)
            stmt = stmt.order_by(ReportKnowledgeTable.created_at).limit(limit)
            rows = session.exec(stmt).all()
        return [ReportKnowledgeAtom.model_validate_json(row.atom_json) for row in rows]

    def save_archetype(self, archetype: ResearchArchetype) -> ResearchArchetype:
        with Session(self.engine) as session:
            row = session.get(ArchetypeTable, archetype.id)
            payload = ArchetypeTable(
                id=archetype.id,
                family=str(archetype.family),
                archetype_json=archetype.model_dump_json(),
                updated_at=archetype.updated_at.isoformat(),
            )
            if row is None:
                session.add(payload)
            else:
                row.family = payload.family
                row.archetype_json = payload.archetype_json
                row.updated_at = payload.updated_at
                session.add(row)
            session.commit()
        return archetype

    def get_archetype(self, archetype_id: str) -> ResearchArchetype | None:
        with Session(self.engine) as session:
            row = session.get(ArchetypeTable, archetype_id)
            if row is None:
                return None
            return ResearchArchetype.model_validate_json(row.archetype_json)

    def save_feedback(self, record: FeedbackRecord) -> FeedbackRecord:
        with Session(self.engine) as session:
            row = session.get(FeedbackMemoryTable, record.id)
            payload = FeedbackMemoryTable(
                id=record.id,
                kind=str(record.kind),
                source=str(record.source),
                mechanism_family=str(record.mechanism_family) if record.mechanism_family else None,
                factor_name=record.factor_name,
                root_cause=record.root_cause,
                failure_type=record.failure_type,
                record_json=record.model_dump_json(),
                created_at=record.created_at.isoformat(),
            )
            if row is None:
                session.add(payload)
            else:
                row.kind = payload.kind
                row.source = payload.source
                row.mechanism_family = payload.mechanism_family
                row.factor_name = payload.factor_name
                row.root_cause = payload.root_cause
                row.failure_type = payload.failure_type
                row.record_json = payload.record_json
                session.add(row)
            session.commit()
        return record

    def query_feedback(self, query: FeedbackQuery | None = None) -> list[FeedbackRecord]:
        q = query or FeedbackQuery()
        with Session(self.engine) as session:
            stmt = select(FeedbackMemoryTable)
            if q.kind is not None:
                stmt = stmt.where(FeedbackMemoryTable.kind == str(q.kind))
            if q.mechanism_family is not None:
                stmt = stmt.where(
                    FeedbackMemoryTable.mechanism_family == str(q.mechanism_family)
                )
            if q.factor_name:
                stmt = stmt.where(FeedbackMemoryTable.factor_name == q.factor_name)
            if q.root_cause:
                stmt = stmt.where(FeedbackMemoryTable.root_cause == q.root_cause)
            if q.failure_type:
                stmt = stmt.where(FeedbackMemoryTable.failure_type == q.failure_type)
            if not q.include_mock:
                stmt = stmt.where(FeedbackMemoryTable.source != str(FeedbackSource.MOCK))
            stmt = stmt.order_by(FeedbackMemoryTable.created_at).limit(q.limit)
            rows = session.exec(stmt).all()
        return [FeedbackRecord.model_validate_json(row.record_json) for row in rows]
