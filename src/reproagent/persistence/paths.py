"""AppPaths：所有文件系统路径约定。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reproagent.settings import Settings


@dataclass(frozen=True)
class AppPaths:
    """~/.reproagent 下的目录与文件约定。"""

    data_dir: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> AppPaths:
        return cls(data_dir=settings.data_dir.expanduser())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "reproagent.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def factors_dir(self) -> Path:
        return self.data_dir / "factors"

    @property
    def wiki_dir(self) -> Path:
        return self.data_dir / "wiki"

    @property
    def wiki_index(self) -> Path:
        return self.wiki_dir / "INDEX.md"

    @property
    def wiki_factors_dir(self) -> Path:
        return self.wiki_dir / "factors"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def report_dir(self, report_id: str) -> Path:
        return self.reports_dir / report_id

    def factor_dir(self, factor_id: str) -> Path:
        return self.factors_dir / factor_id

    def cache_entry_dir(self, cache_key: str) -> Path:
        return self.cache_dir / cache_key

    def ensure_layout(self) -> None:
        """创建顶层目录结构。"""
        for d in (
            self.cache_dir,
            self.reports_dir,
            self.factors_dir,
            self.wiki_dir,
            self.wiki_factors_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
