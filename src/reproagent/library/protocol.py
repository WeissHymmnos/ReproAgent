"""FactorLibrary Protocol。"""

from __future__ import annotations

from typing import Protocol

from reproagent.models.library import FactorLibraryEntry, LibraryFilter


class FactorLibraryProtocol(Protocol):
    def register(self, entry: FactorLibraryEntry) -> FactorLibraryEntry:
        """持久化 + 去重检查 + 版本 bump。副作用：更新 INDEX.md 和 wiki。"""
        ...

    def get(self, factor_id: str) -> FactorLibraryEntry | None: ...

    def list(self, filter: LibraryFilter | None = None) -> list[FactorLibraryEntry]: ...  # noqa: A002

    def dedup_check(self, entry: FactorLibraryEntry) -> FactorLibraryEntry | None:
        """dedup_hash 命中 → 返回已有 entry，否则 None。"""
        ...

    def update_index(self) -> None:
        """从全部 entries 重生成全局 INDEX.md。"""
        ...

    def update_wiki(self) -> None:
        """从 entries 生成逐因子 Markdown wiki 页。"""
        ...
