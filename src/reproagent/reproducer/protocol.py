"""因子计算引擎与复现编排 Protocol。"""

from __future__ import annotations

from datetime import date
from typing import Protocol

import polars as pl

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig


class FactorEngine(Protocol):
    """可插拔计算引擎（Polars 或 rqalpha）。"""

    def compute(
        self,
        factor_def: FactorDefinition,
        universe: str,
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """返回 DataFrame：列 [date, asset, factor_value]，按 date, asset 排序。"""
        ...


class FactorReproducerProtocol(Protocol):
    def reproduce(self, config: ReplicationConfig) -> BacktestResult:
        """全流程：计算因子 → 回测 → 指标 → 图表。单次调用一个因子。"""
        ...

    def compute_factor(
        self,
        config: ReplicationConfig,
        spec: ParsedFactorSpec,
    ) -> tuple[FactorDefinition, pl.DataFrame]:
        """返回 (规范化 FactorDefinition, 因子值 DataFrame)。"""
        ...
