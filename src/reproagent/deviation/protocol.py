"""DeviationAnalyzer Protocol。"""

from __future__ import annotations

from typing import Protocol

from reproagent.models.backtest import BacktestResult
from reproagent.models.deviation import DeviationReport, RootCause, ToleranceConfig
from reproagent.models.reflection import ReflectionState
from reproagent.models.replication import ReplicationConfig
from reproagent.models.report import ReportedMetrics


class DeviationAnalyzerProtocol(Protocol):
    def analyze(
        self,
        reproduced: BacktestResult,
        reported: ReportedMetrics,
        tolerances: ToleranceConfig,
    ) -> DeviationReport:
        """对比复现值 vs 研报值，设置 .passed 和 .metric_deviations。"""
        ...

    def classify_root_cause(
        self,
        deviation: DeviationReport,
        config: ReplicationConfig,
    ) -> RootCause:
        """分类偏差根因，复杂情况可调 LLM。"""
        ...

    def should_reflect(
        self,
        deviation: DeviationReport,
        state: ReflectionState,
    ) -> bool:
        """True = 根因可修正 AND 还有迭代次数 AND 偏差仍在改善。"""
        ...
