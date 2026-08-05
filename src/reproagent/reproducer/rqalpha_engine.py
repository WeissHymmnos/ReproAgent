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
        data: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """返回 [date, asset, factor_value]。"""
        try:
            import rqalpha  # noqa: F401
        except ImportError:
            from reproagent.exceptions import ConfigurationError

            raise ConfigurationError(
                "rqalpha is not installed. Please install with `pip install rqalpha`."
            )

        # Fallback to PolarsEngine for now
        from reproagent.reproducer.polars_engine import PolarsEngine

        engine = PolarsEngine(self.config)
        return engine.compute(factor_def, universe, start, end, data)
