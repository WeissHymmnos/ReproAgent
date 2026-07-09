"""FactorLibraryManager：register / get / list。"""

from __future__ import annotations

from reproagent.library.classifier import StyleClassifier
from reproagent.library.index_writer import IndexWriter
from reproagent.library.wiki_writer import WikiWriter
from reproagent.models.library import FactorLibraryEntry, LibraryFilter
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository


class FactorLibraryManager:
    """实现 FactorLibraryProtocol。"""

    def __init__(self, repository: Repository, paths: AppPaths) -> None:
        self.repository = repository
        self.paths = paths
        self.classifier = StyleClassifier()
        self.index_writer = IndexWriter(paths)
        self.wiki_writer = WikiWriter(paths)

    def register(self, entry: FactorLibraryEntry) -> FactorLibraryEntry:
        """去重 → 分类 → 入库 → 更新 INDEX / wiki。"""
        raise NotImplementedError("FactorLibraryManager.register")

    def get(self, factor_id: str) -> FactorLibraryEntry | None:
        raise NotImplementedError("FactorLibraryManager.get")

    def list(  # noqa: A003
        self, filter: LibraryFilter | None = None  # noqa: A002
    ) -> list[FactorLibraryEntry]:
        raise NotImplementedError("FactorLibraryManager.list")

    def dedup_check(self, entry: FactorLibraryEntry) -> FactorLibraryEntry | None:
        raise NotImplementedError("FactorLibraryManager.dedup_check")

    def update_index(self) -> None:
        raise NotImplementedError("FactorLibraryManager.update_index")

    def update_wiki(self) -> None:
        raise NotImplementedError("FactorLibraryManager.update_wiki")
