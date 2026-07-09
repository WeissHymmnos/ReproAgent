"""CacheManager：命中/未命中与落盘。"""

from __future__ import annotations

from pathlib import Path

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
from reproagent.persistence.paths import AppPaths


class CacheManager:
    """文件系统缓存：~/.reproagent/cache/<cache_key>/。"""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def get_cached(
        self, cache_key: str
    ) -> tuple[str, list[ParsedFactorSpec], ReplicationConfig] | None:
        """命中 → (markdown, specs, config)；未命中 → None。"""
        raise NotImplementedError("CacheManager.get_cached")

    def get_cached_backtest(
        self, cache_key: str, factor_id: str
    ) -> BacktestResult | None:
        """命中 → 缓存回测结果；否则 None。"""
        raise NotImplementedError("CacheManager.get_cached_backtest")

    def save(
        self,
        cache_key: str,
        markdown: str,
        specs: list[ParsedFactorSpec],
        config: ReplicationConfig,
        backtest_result: BacktestResult | None = None,
    ) -> None:
        """保存缓存到 cache/<cache_key>/。"""
        raise NotImplementedError("CacheManager.save")

    def cache_dir(self, cache_key: str) -> Path:
        return self.paths.cache_entry_dir(cache_key)
