"""生成逐因子 Markdown wiki 页。"""

from __future__ import annotations

from reproagent.models.library import FactorLibraryEntry
from reproagent.persistence.paths import AppPaths


class WikiWriter:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def update(self, entries: list[FactorLibraryEntry] | None = None) -> None:
        """为每个因子生成 wiki/factors/<factor_name>.md。"""
        raise NotImplementedError("WikiWriter.update")

    def write_entry(self, entry: FactorLibraryEntry) -> None:
        """写入单个因子 wiki 页。"""
        raise NotImplementedError("WikiWriter.write_entry")
