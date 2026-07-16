"""FactorLibraryManager：register / get / list。"""

from __future__ import annotations

from reproagent.library.classifier import StyleClassifier
from reproagent.library.index_writer import IndexWriter
from reproagent.library.versioning import bump, compute_dedup_hash
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
        entry.dedup_hash = compute_dedup_hash(entry.factor)
        existing = self.dedup_check(entry)
        if existing is not None:
            entry.version = bump(existing.version, "patch")
            entry.id = existing.id
        classified_style = self.classifier.classify(entry.factor)
        entry.factor = entry.factor.model_copy(update={"style": classified_style})
        saved = self.repository.save_library_entry(entry)
        self.update_index()
        self.update_wiki()
        return saved

    def get(self, factor_id: str) -> FactorLibraryEntry | None:
        return self.repository.get_library_entry(factor_id)

    def list(  # noqa: A003
        self, filter: LibraryFilter | None = None  # noqa: A002
    ) -> list[FactorLibraryEntry]:
        return self.repository.list_library_entries(filter)

    def dedup_check(self, entry: FactorLibraryEntry) -> FactorLibraryEntry | None:
        return self.repository.get_by_dedup_hash(entry.dedup_hash)

    def update_index(self) -> None:
        entries = self.repository.list_library_entries()
        self.index_writer.update(entries)

    def update_wiki(self) -> None:
        entries = self.repository.list_library_entries()
        self.wiki_writer.update(entries)