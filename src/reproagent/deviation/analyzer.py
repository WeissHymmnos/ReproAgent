"""DeviationAnalyzer：对比 + 容忍检查。"""

from __future__ import annotations

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
        """对比复现值 vs 研报值。"""
        raise NotImplementedError("DeviationAnalyzer.analyze")

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
        """是否进入/继续反思循环。"""
        raise NotImplementedError("DeviationAnalyzer.should_reflect")
