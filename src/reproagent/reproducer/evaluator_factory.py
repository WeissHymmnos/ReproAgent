"""build_evaluator(config) → FactorEngine。"""

from __future__ import annotations

from reproagent.models.replication import ReplicationConfig
from reproagent.reproducer.protocol import FactorEngine


def build_evaluator(config: ReplicationConfig) -> FactorEngine:
    """按 config.engine 创建 PolarsEngine 或 RiceQuantEval。"""
    if config.engine == "polars":
        from reproagent.reproducer.polars_engine import PolarsEngine

        return PolarsEngine(config)
    if config.engine == "rqalpha":
        from reproagent.reproducer.rqalpha_engine import RiceQuantEval

        return RiceQuantEval(config)
    raise ValueError(f"未知引擎: {config.engine}")
