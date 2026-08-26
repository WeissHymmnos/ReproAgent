"""rqalpha 因子计算引擎（RiceQuantEval 命名对齐 flowchart）。"""

from __future__ import annotations

from datetime import date

import polars as pl

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import ReplicationConfig


class RiceQuantEval:
    """rqalpha 引擎占位。compute() 直接报错，避免静默改用 Polars。"""

    def __init__(self, config: ReplicationConfig) -> None:
        self.config = config

    def compute(
        self,
        factor_def: FactorDefinition,
        universe: str,
        start: date,
        end: date,
        data: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """未实现。"""
        del factor_def, universe, start, end, data
        from reproagent.exceptions import ConfigurationError

        raise ConfigurationError(
            "engine=rqalpha is not implemented; use engine=polars"
        )
