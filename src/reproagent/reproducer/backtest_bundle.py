"""Shipped assembly: DataLoader + PolarsEngine + StrategyBacktester.

Used by finaince eval and by FastMCP run_backtest. Not a reimplementation of
``evaluator_factory.build_evaluator``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from reproagent.models.factor_def import FactorDefinition
from reproagent.models.replication import BacktestParams, ReplicationConfig
from reproagent.reproducer.backtester import StrategyBacktester
from reproagent.reproducer.data_loader import DataLoader
from reproagent.reproducer.polars_engine import PolarsEngine
from reproagent.settings import Settings, get_settings


def build_backtest_bundle(
    expression: str,
    *,
    start_date: str = "2023-01-02",
    end_date: str = "2023-02-10",
    universe: str = "csi300",
    num_groups: int = 5,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run the real local/polars backtest path and return numeric metrics."""
    cfg = settings or get_settings()
    loader = DataLoader(cfg)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    fdef = FactorDefinition(
        id="eval-backtest",
        spec_id="eval",
        name="eval_factor",
        name_cn="Eval因子",
        style="other",
        formula=expression,
        input_fields=[],
        universe=universe,
        rebalance_frequency="monthly",
    )
    data = loader.load_price_data(universe, start, end)
    rcfg = ReplicationConfig(
        id="eval",
        report_id="eval",
        factor_specs=[],
        engine="polars",
        data_source=cfg.data_source,  # type: ignore[arg-type]
        backtest_params=BacktestParams(start_date=start, end_date=end),
        parser_version=cfg.parser_version,
        extraction_model_id="eval",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(rcfg, allow_formula_fallback=False)
    fv = engine.compute(fdef, universe, start, end, data=data)
    bt = StrategyBacktester(cfg).run(
        factor_values=fv,
        params=BacktestParams(start_date=start, end_date=end, num_groups=num_groups),
        factor_def=fdef,
        data=data,
    )
    return {
        "backtest_id": bt.id,
        "rows": len(fv),
        "ic_mean": bt.ic_mean,
        "ic_ir": bt.ic_ir,
        "sharpe_ratio": bt.sharpe_ratio,
        "max_drawdown": bt.max_drawdown,
        "long_short_annual_return": bt.long_short_annual_return,
        "factor_values_path": str(bt.factor_values_path),
        "equity_curve_path": str(bt.equity_curve_path),
    }
