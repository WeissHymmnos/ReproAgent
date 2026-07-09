"""分组回测 + IC。"""

from __future__ import annotations

import polars as pl

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams
from reproagent.settings import Settings


class StrategyBacktester:
    """分组回测 + IC 计算。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run(
        self,
        factor_values: pl.DataFrame,
        params: BacktestParams,
        factor_def: FactorDefinition,
    ) -> BacktestResult:
        """分组收益、IC、夏普、回撤；落盘 parquet 后返回 BacktestResult。"""
        raise NotImplementedError("StrategyBacktester.run")
