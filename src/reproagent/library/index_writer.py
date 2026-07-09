"""重生成全局 INDEX.md。"""

from __future__ import annotations

from reproagent.models.library import FactorLibraryEntry
from reproagent.persistence.paths import AppPaths


class IndexWriter:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def update(self, entries: list[FactorLibraryEntry] | None = None) -> None:
        """重生成 wiki/INDEX.md 表格（按 created_at 倒序）。"""
        raise NotImplementedError("IndexWriter.update")
