"""rqalpha 因子计算引擎（RiceQuantEval 命名对齐 flowchart）。"""

from __future__ import annotations

from datetime import date

import polars as pl

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import ReplicationConfig


class RiceQuantEval:
    """用 rqalpha 计算因子值。实现 FactorEngine Protocol。

    注意：rqalpha 为 optional extra，实现时 lazy import。
    """

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
        raise NotImplementedError("RiceQuantEval.compute")
