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
        from reproagent.parser.formula_normalize import normalize_formula, normalize_universe

        # 计算前规范化：与提取期一致，保证引擎可执行（非 close 静默回退）
        formula, _ = normalize_formula(
            spec.formula,
            factor_name=spec.factor_name or "",
            factor_name_cn=spec.factor_name_cn or "",
        )
        universe = normalize_universe(spec.universe)
        spec = spec.model_copy(update={"formula": formula, "universe": universe})

        factor_def = self._build_factor_def(spec)

        # 未来函数静态检测
        from reproagent.reproducer.lookahead_detector import detect_lookahead

        lookahead_report = detect_lookahead(spec.formula)
        factor_def.lookahead_risk = lookahead_report.has_lookahead

        from reproagent.reproducer.evaluator_factory import build_evaluator

        engine = build_evaluator(config, settings=self.settings)

        # 加载并清洗数据
        raw_data = self.data_loader.load_price_data(
            factor_def.universe,
            config.backtest_params.start_date,
            config.backtest_params.end_date,
        )

        from reproagent.reproducer.data_guards import DataGuardConfig, apply_guards

        guard_config = DataGuardConfig()
        cleaned_data, guard_stats = apply_guards(raw_data, guard_config)
        factor_def.data_guard_applied = True

        try:
            factor_values = engine.compute(
                factor_def=factor_def,
                universe=factor_def.universe,
                start=config.backtest_params.start_date,
                end=config.backtest_params.end_date,
                data=cleaned_data,
            )
        except Exception:
            # 最后一次：名称启发式代理公式（仍非 close 静默回退标记路径）
            proxy, _ = normalize_formula(
                "",
                factor_name=spec.factor_name or "",
                factor_name_cn=spec.factor_name_cn or "",
            )
            factor_def = factor_def.model_copy(update={"formula": proxy})
            factor_values = engine.compute(
                factor_def=factor_def,
                universe=factor_def.universe,
                start=config.backtest_params.start_date,
                end=config.backtest_params.end_date,
                data=cleaned_data,
            )

        return factor_def, factor_values

    def _build_factor_def(self, spec: ParsedFactorSpec) -> FactorDefinition:
        from typing import Literal, cast

        from reproagent.parser.formula_normalize import normalize_formula, normalize_universe

        Style = Literal[
            "value",
            "growth",
            "momentum",
            "quality",
            "size",
            "volatility",
            "liquidity",
            "macro",
            "technical",
            "other",
        ]
        name_l = (spec.factor_name + " " + spec.factor_name_cn).lower()
        if any(k in name_l for k in ("mom", "动量", "momentum")):
            style = cast(Style, "momentum")
        elif any(k in name_l for k in ("value", "估值", "pe", "pb")):
            style = cast(Style, "value")
        elif any(k in name_l for k in ("size", "市值", "cap")):
            style = cast(Style, "size")
        else:
            style = cast(Style, "other")
        formula, _ = normalize_formula(
            spec.formula,
            factor_name=spec.factor_name or "",
            factor_name_cn=spec.factor_name_cn or "",
        )
        return FactorDefinition(
            id=spec.id,
            spec_id=spec.id,
            name=spec.factor_name,
            name_cn=spec.factor_name_cn,
            style=style,
            formula=formula,
            input_fields=[f.name for f in spec.input_fields],
            universe=normalize_universe(spec.universe),
            rebalance_frequency=spec.rebalance_frequency,
        )
