"""Polars 因子计算引擎。"""

from __future__ import annotations

from datetime import date

import polars as pl

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import ReplicationConfig


class PolarsEngine:
    """实现 FactorEngine Protocol。用 Polars lazy API 计算因子。"""

    def __init__(self, config: ReplicationConfig) -> None:
        self.config = config

    def compute(
        self,
        factor_def: FactorDefinition,
        universe: str,
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """返回 [date, asset, factor_value]。"""
        raise NotImplementedError("PolarsEngine.compute")
