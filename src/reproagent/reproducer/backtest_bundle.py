"""DataLoader + PolarsEngine + StrategyBacktester used by MCP run_backtest."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

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
    transaction_cost_bps: float | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run the local/polars backtest path and return numeric metrics."""
    cfg = settings or get_settings()
    loader = DataLoader(cfg)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    cost = 3.0 if transaction_cost_bps is None else float(transaction_cost_bps)
    params = BacktestParams(
        start_date=start,
        end_date=end,
        num_groups=num_groups,
        transaction_cost_bps=cost,
    )
    run_id = uuid4().hex[:12]
    fdef = FactorDefinition(
        id=f"eval-{run_id}",
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
        backtest_params=params,
        parser_version=cfg.parser_version,
        extraction_model_id="eval",
        created_at=datetime.now(UTC),
    )
    engine = PolarsEngine(rcfg, allow_formula_fallback=False)
    fv = engine.compute(fdef, universe, start, end, data=data)
    bt = StrategyBacktester(cfg).run(
        factor_values=fv,
        params=params,
        factor_def=fdef,
        data=data,
    )
    mean_factor = 0.0
    if len(fv) > 0 and "factor_value" in fv.columns:
        _m = fv["factor_value"].drop_nulls().mean()
        mean_factor = float(_m) if isinstance(_m, (int, float)) else 0.0
    return {
        "backtest_id": bt.id,
        "rows": len(fv),
        "mean_factor": mean_factor,
        "ic_mean": bt.ic_mean,
        "ic_ir": bt.ic_ir,
        "sharpe_ratio": bt.sharpe_ratio,
        "max_drawdown": bt.max_drawdown,
        "long_short_annual_return": bt.long_short_annual_return,
        "factor_values_path": str(bt.factor_values_path),
        "equity_curve_path": str(bt.equity_curve_path),
        "transaction_cost_bps": float(params.transaction_cost_bps),
    }
