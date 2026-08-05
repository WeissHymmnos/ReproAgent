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
from reproagent.models.reflection import ReflectionState, ReflectionStep
from reproagent.models.report import ResearchReport
from reproagent.persistence.tables import (
    FactorLibraryTable,
    ManualReviewQueueTable,
    ReflectionStateTable,
    ReportTable,
)


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

    def enqueue_review(self, report_id: str, reason: str) -> str:
        entry_id = uuid4().hex
        with Session(self.engine) as session:
            row = ManualReviewQueueTable(
                id=entry_id,
                report_id=report_id,
                reason=reason,
                status="pending",
                created_at=_now_iso(),
            )
            session.add(row)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"enqueue_review failed: {exc}") from exc
        return entry_id

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

    def update_review_status(self, entry_id: str, status: str) -> None:
        with Session(self.engine) as session:
            row = session.get(ManualReviewQueueTable, entry_id)
            if row is None:
                raise PersistenceError(f"update_review_status: entry {entry_id} not found")
            row.status = status
            session.add(row)
            try:
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                raise PersistenceError(f"update_review_status failed: {exc}") from exc
