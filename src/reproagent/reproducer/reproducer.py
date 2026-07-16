"""FactorReproducer 编排器。"""

from __future__ import annotations

import polars as pl

from reproagent.models.backtest import BacktestResult
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.replication import ReplicationConfig
from reproagent.reproducer.backtester import StrategyBacktester
from reproagent.reproducer.data_loader import DataLoader
from reproagent.settings import Settings


class FactorReproducer:
    """实现 FactorReproducerProtocol。编排计算 → 回测 → 指标全流程。"""

    def __init__(self, settings: Settings, data_loader: DataLoader) -> None:
        self.settings = settings
        self.data_loader = data_loader
        self.backtester = StrategyBacktester(settings)

    def reproduce(self, config: ReplicationConfig) -> BacktestResult:
        """全流程：计算因子 → 回测 → 指标。"""
        if not config.factor_specs:
            from reproagent.exceptions import ReproductionError
            raise ReproductionError("No factor specs provided in config.")
            
        spec = config.factor_specs[0]
        factor_def, factor_values = self.compute_factor(config, spec)
        
        prices = self.data_loader.load_price_data(
            factor_def.universe,
            config.backtest_params.start_date,
            config.backtest_params.end_date,
        )
        
        return self.backtester.run(
            factor_values=factor_values,
            params=config.backtest_params,
            factor_def=factor_def,
            data=prices,
        )

    def compute_factor(
        self,
        config: ReplicationConfig,
        spec: ParsedFactorSpec,
    ) -> tuple[FactorDefinition, pl.DataFrame]:
        """返回 (FactorDefinition, 因子值 DataFrame)。"""
        factor_def = self._build_factor_def(spec)
        
        from reproagent.reproducer.evaluator_factory import build_evaluator
        engine = build_evaluator(config)
        
        factor_values = engine.compute(
            factor_def=factor_def,
            universe=factor_def.universe,
            start=config.backtest_params.start_date,
            end=config.backtest_params.end_date,
        )
        
        return factor_def, factor_values

    def _build_factor_def(self, spec: ParsedFactorSpec) -> FactorDefinition:
        style = "momentum" if "mom" in spec.factor_name.lower() else "other"
        return FactorDefinition(
            id=spec.id,
            spec_id=spec.id,
            name=spec.factor_name,
            name_cn=spec.factor_name_cn,
            style=style,
            formula=spec.formula,
            input_fields=[f.name for f in spec.input_fields],
            universe=spec.universe,
            rebalance_frequency=spec.rebalance_frequency,
        )
