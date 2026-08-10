"""MemoryStore：研究记忆读写门面（Phase 0）。

后续 Phase 会在 pipeline / reflection / review 中调用；当前仅提供 API。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from reproagent.models.memory import (
    FeedbackQuery,
    FeedbackRecord,
    ReportKnowledgeAtom,
    ResearchArchetype,
)

if TYPE_CHECKING:
    from reproagent.persistence.repository import Repository


class MemoryStore:
    """封装 Repository 上的记忆表操作。"""

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    def save_knowledge(self, atom: ReportKnowledgeAtom) -> ReportKnowledgeAtom:
        return self._repo.save_knowledge_atom(atom)

    def list_knowledge(
        self, report_id: str | None = None, *, limit: int = 100
    ) -> list[ReportKnowledgeAtom]:
        return self._repo.list_knowledge_atoms(report_id, limit=limit)

    def save_archetype(self, archetype: ResearchArchetype) -> ResearchArchetype:
        return self._repo.save_archetype(archetype)

    def get_archetype(self, archetype_id: str) -> ResearchArchetype | None:
        return self._repo.get_archetype(archetype_id)

    def save_feedback(self, record: FeedbackRecord) -> FeedbackRecord:
        return self._repo.save_feedback(record)

    def query_feedback(self, query: FeedbackQuery | None = None) -> list[FeedbackRecord]:
        return self._repo.query_feedback(query)
