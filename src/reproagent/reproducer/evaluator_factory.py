"""build_evaluator(config) → FactorEngine。"""

from __future__ import annotations

from reproagent.models.replication import ReplicationConfig
from reproagent.reproducer.protocol import FactorEngine
from reproagent.settings import Settings, get_settings


def build_evaluator(
    config: ReplicationConfig,
    settings: Settings | None = None,
) -> FactorEngine:
    """按 config.engine 创建 PolarsEngine 或 RiceQuantEval。"""
    settings = settings or get_settings()
    if config.engine == "polars":
        from reproagent.reproducer.polars_engine import PolarsEngine

        return PolarsEngine(
            config,
            allow_formula_fallback=settings.formula_fallback_allowed,
        )
    if config.engine == "rqalpha":
        from reproagent.reproducer.rqalpha_engine import RiceQuantEval

        return RiceQuantEval(config)
    raise ValueError(f"未知引擎: {config.engine}")
