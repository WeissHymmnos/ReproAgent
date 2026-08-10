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
        from reproagent.parser.formula_normalize import normalize_all
        from reproagent.reproducer.run_flags import mark_formula_proxy, mark_universe_fallback

        allow_proxy = bool(self.settings.formula_fallback_allowed)
        nr = normalize_all(
            formula=spec.formula,
            universe=spec.universe,
            factor_name=spec.factor_name or "",
            factor_name_cn=spec.factor_name_cn or "",
            allow_proxy=allow_proxy,
        )
        if nr.used_proxy:
            mark_formula_proxy(spec.factor_name or "", "compute_proxy")
            if not allow_proxy:
                from reproagent.exceptions import ReproductionError

                raise ReproductionError(
                    f"Strict mode: proxy formula rejected for {spec.factor_name!r}"
                )
        uni = nr.universe
        if nr.universe_fallback:
            mark_universe_fallback(f"compute:{spec.universe!r}->{nr.universe}")
            if not allow_proxy:
                from reproagent.exceptions import ReproductionError

                raise ReproductionError(
                    f"Strict mode: universe fallback rejected for {spec.factor_name!r} "
                    f"({spec.universe!r}→{nr.universe})"
                )
        spec = spec.model_copy(update={"formula": nr.formula, "universe": uni})

        factor_def = self._build_factor_def(spec)

        from reproagent.reproducer.lookahead_detector import detect_lookahead

        lookahead_report = detect_lookahead(spec.formula)
        factor_def.lookahead_risk = lookahead_report.has_lookahead

        from reproagent.reproducer.evaluator_factory import build_evaluator

        engine = build_evaluator(config, settings=self.settings)

        raw_data = self.data_loader.load_price_data(
            factor_def.universe,
            config.backtest_params.start_date,
            config.backtest_params.end_date,
        )

        from reproagent.reproducer.data_guards import DataGuardConfig, apply_guards

        guard_config = DataGuardConfig()
        cleaned_data, guard_stats = apply_guards(raw_data, guard_config)
        factor_def.data_guard_applied = True

        # 严格模式：失败即抛出，不做名称代理重试
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

        from reproagent.parser.formula_normalize import normalize_all

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
        nr = normalize_all(
            formula=spec.formula,
            universe=spec.universe,
            factor_name=spec.factor_name or "",
            factor_name_cn=spec.factor_name_cn or "",
            allow_proxy=bool(self.settings.formula_fallback_allowed),
        )
        return FactorDefinition(
            id=spec.id,
            spec_id=spec.id,
            name=spec.factor_name,
            name_cn=spec.factor_name_cn,
            style=style,
            formula=nr.formula,
            input_fields=[f.name for f in spec.input_fields],
            universe=nr.universe,
            rebalance_frequency=spec.rebalance_frequency,
        )
