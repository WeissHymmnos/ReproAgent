"""领域模型 CRUD 仓储。"""

from __future__ import annotations

from typing import Any

from reproagent.models.library import FactorLibraryEntry, LibraryFilter
from reproagent.models.reflection import ReflectionState, ReflectionStep
from reproagent.models.report import ResearchReport


class Repository:
    """通用 CRUD：save/load 领域模型（实现时映射 tables.py）。"""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # --- reports ---

    def save_report(self, report: ResearchReport) -> ResearchReport:
        raise NotImplementedError("Repository.save_report")

    def get_report(self, report_id: str) -> ResearchReport | None:
        raise NotImplementedError("Repository.get_report")

    def get_report_by_hash(self, file_hash: str) -> ResearchReport | None:
        raise NotImplementedError("Repository.get_report_by_hash")

    # --- library ---

    def save_library_entry(self, entry: FactorLibraryEntry) -> FactorLibraryEntry:
        raise NotImplementedError("Repository.save_library_entry")

    def get_library_entry(self, entry_id: str) -> FactorLibraryEntry | None:
        raise NotImplementedError("Repository.get_library_entry")

    def list_library_entries(
        self, filter_: LibraryFilter | None = None
    ) -> list[FactorLibraryEntry]:
        raise NotImplementedError("Repository.list_library_entries")

    def get_by_dedup_hash(self, dedup_hash: str) -> FactorLibraryEntry | None:
        raise NotImplementedError("Repository.get_by_dedup_hash")

    # --- reflection ---

    def save_reflection_state(self, state: ReflectionState) -> ReflectionState:
        raise NotImplementedError("Repository.save_reflection_state")

    def get_reflection_state(self, state_id: str) -> ReflectionState | None:
        raise NotImplementedError("Repository.get_reflection_state")

    def save_reflection_step(self, step: ReflectionStep) -> ReflectionStep:
        raise NotImplementedError("Repository.save_reflection_step")

    # --- review queue ---

    def enqueue_review(self, report_id: str, reason: str) -> str:
        """返回 queue_entry_id。"""
        raise NotImplementedError("Repository.enqueue_review")

    def dequeue_review(self) -> tuple[str, str, str] | None:
        """(entry_id, report_id, reason) 或 None。"""
        raise NotImplementedError("Repository.dequeue_review")

    def update_review_status(self, entry_id: str, status: str) -> None:
        raise NotImplementedError("Repository.update_review_status")
