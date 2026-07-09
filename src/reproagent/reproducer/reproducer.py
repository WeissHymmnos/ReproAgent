"""FactorReproducer 编排器。"""

from __future__ import annotations

import polars as pl

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
from reproagent.reproducer.backtester import StrategyBacktester
from reproagent.reproducer.data_loader import DataLoader
from reproagent.settings import Settings


class FactorReproducer:
    """实现 FactorReproducerProtocol。编排计算 → 回测 → 指标全流程。"""

    def __init__(self, settings: Settings, data_loader: DataLoader) -> None:
        self.settings = settings
        self.data_loader = data_loader
        self.backtester = StrategyBacktester(settings)

    def reproduce(self, config: ReplicationConfig) -> BacktestResult:
        """全流程：计算因子 → 回测 → 指标。"""
        raise NotImplementedError("FactorReproducer.reproduce")

    def compute_factor(
        self,
        config: ReplicationConfig,
        spec: ParsedFactorSpec,
    ) -> tuple[FactorDefinition, pl.DataFrame]:
        """返回 (FactorDefinition, 因子值 DataFrame)。"""
        raise NotImplementedError("FactorReproducer.compute_factor")

    def _build_factor_def(self, spec: ParsedFactorSpec) -> FactorDefinition:
        raise NotImplementedError("FactorReproducer._build_factor_def")
