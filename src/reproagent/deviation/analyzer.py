"""DeviationAnalyzer：对比 + 容忍检查。"""

from __future__ import annotations

from uuid import uuid4

from reproagent.models.backtest import BacktestResult
from reproagent.models.deviation import DeviationReport, RootCause, ToleranceConfig
from reproagent.models.reflection import ReflectionState
from reproagent.models.replication import ReplicationConfig
from reproagent.models.report import ReportedMetrics


class DeviationAnalyzer:
    """实现 DeviationAnalyzerProtocol。"""

    def analyze(
        self,
        reproduced: BacktestResult,
        reported: ReportedMetrics,
        tolerances: ToleranceConfig,
    ) -> DeviationReport:
        """对比复现值 vs 研报值，设置 .passed 和 .metric_deviations。"""
        metric_deviations: dict[str, float] = {}
        passed_flags: list[bool] = []

        if reported.ic_mean is not None:
            delta = reproduced.ic_mean - reported.ic_mean
            metric_deviations["ic_mean"] = delta
            passed_flags.append(abs(delta) <= tolerances.ic_mean_abs)

        if reported.ic_ir is not None:
            delta = reproduced.ic_ir - reported.ic_ir
            metric_deviations["ic_ir"] = delta
            passed_flags.append(abs(delta) <= tolerances.ic_ir_abs)

        if reported.long_short_return is not None:
            delta = reproduced.long_short_annual_return - reported.long_short_return
            metric_deviations["long_short_annual_return"] = delta
            if tolerances.long_short_return_rel > 0 and reported.long_short_return != 0:
                rel = abs(delta) / abs(reported.long_short_return)
                passed_flags.append(rel <= tolerances.long_short_return_rel)
            else:
                passed_flags.append(abs(delta) <= 5.0)

        if reported.sharpe_ratio is not None:
            delta = reproduced.sharpe_ratio - reported.sharpe_ratio
            metric_deviations["sharpe_ratio"] = delta
            passed_flags.append(abs(delta) <= tolerances.sharpe_abs)

        if reported.max_drawdown is not None:
            delta = reproduced.max_drawdown - reported.max_drawdown
            metric_deviations["max_drawdown"] = delta
            passed_flags.append(abs(delta) <= tolerances.max_drawdown_abs)

        # 无研报对照指标时，不能 vacuous pass：必须因子值可用且指标非全零退化
        from reproagent.reproducer.health import is_healthy_reproduction

        healthy = is_healthy_reproduction(reproduced)
        if passed_flags:
            passed = all(passed_flags) and healthy
        else:
            # no-GT 路径：健康复现即通过
            passed = healthy
            if not healthy:
                metric_deviations["reproduction_health"] = 0.0

        return DeviationReport(
            id=uuid4().hex,
            comparison_id=uuid4().hex,
            factor_id=reproduced.factor_id,
            passed=passed,
            metric_deviations=metric_deviations,
            tolerances=tolerances,
            root_cause=RootCause.UNKNOWN,
            root_cause_detail="" if passed else (
                "" if passed_flags else "unhealthy_or_degenerate_reproduction"
            ),
            recommend_reflect=not passed,
        )

    def classify_root_cause(
        self,
        deviation: DeviationReport,
        config: ReplicationConfig,
    ) -> RootCause:
        """委托 root_cause.classify_root_cause。"""
        from reproagent.deviation.root_cause import classify_root_cause

        return classify_root_cause(deviation, config)

    def should_reflect(
        self,
        deviation: DeviationReport,
        state: ReflectionState,
    ) -> bool:
        """True = 偏差未通过 AND 还有迭代次数 AND 状态仍 in_progress。"""
        if deviation.passed:
            return False
        if state.status != "in_progress":
            return False
        return state.current_iteration < state.max_iterations
