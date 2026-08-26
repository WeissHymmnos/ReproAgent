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

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def memory_feedback_good_dir(self) -> Path:
        return self.memory_dir / "feedback" / "good"

    @property
    def memory_feedback_bad_dir(self) -> Path:
        return self.memory_dir / "feedback" / "bad"

    @property
    def memory_knowledge_dir(self) -> Path:
        return self.memory_dir / "knowledge"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def report_dir(self, report_id: str) -> Path:
        return self.reports_dir / report_id

    def factor_dir(self, factor_id: str) -> Path:
        return self.factors_dir / factor_id

    def cache_entry_dir(self, cache_key: str) -> Path:
        return self.cache_dir / cache_key

    def ensure_layout(self) -> None:
        """创建顶层目录结构；不可写时抛出干净的 ConfigurationError。"""
        from reproagent.exceptions import ConfigurationError

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for d in (
                self.cache_dir,
                self.reports_dir,
                self.factors_dir,
                self.wiki_dir,
                self.wiki_factors_dir,
                self.logs_dir,
                self.memory_dir,
                self.memory_feedback_good_dir,
                self.memory_feedback_bad_dir,
                self.memory_knowledge_dir,
                self.runs_dir,
            ):
                d.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ConfigurationError(
                f"data_dir is not writable: {self.data_dir} — "
                "fix permissions or point DATA_DIR at a writable location"
            ) from exc
