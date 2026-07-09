"""ReflectionLoopController：N≤3、持久化、防震荡。"""

from __future__ import annotations

from reproagent.deviation.protocol import DeviationAnalyzerProtocol
from reproagent.models.deviation import DeviationReport, ToleranceConfig
from reproagent.models.reflection import ReflectionState
from reproagent.models.replication import ReplicationConfig
from reproagent.models.report import ReportedMetrics
from reproagent.parser.config_builder import ConfigBuilder
from reproagent.parser.llm_extractor import LLMExtractor
from reproagent.persistence.repository import Repository
from reproagent.reproducer.protocol import FactorReproducerProtocol


class ReflectionLoopController:
    """有界反思循环：max_iterations=3，连续 2 次无改善则 escalate。"""

    def __init__(
        self,
        reproducer: FactorReproducerProtocol,
        analyzer: DeviationAnalyzerProtocol,
        llm_extractor: LLMExtractor,
        config_builder: ConfigBuilder,
        tolerances: ToleranceConfig,
        repository: Repository,
    ) -> None:
        self.reproducer = reproducer
        self.analyzer = analyzer
        self.llm_extractor = llm_extractor
        self.config_builder = config_builder
        self.tolerances = tolerances
        self.repository = repository

    def run(
        self,
        initial_config: ReplicationConfig,
        reported: ReportedMetrics,
    ) -> ReflectionState:
        """执行反思循环，返回最终 ReflectionState。"""
        raise NotImplementedError("ReflectionLoopController.run")

    def _deviation_score(self, deviation: DeviationReport) -> float:
        """归一化偏差得分：各指标偏差/容忍度的平方和开方。"""
        raise NotImplementedError("ReflectionLoopController._deviation_score")

    def _build_reflection_prompt(
        self,
        state: ReflectionState,
        latest_deviation: DeviationReport,
    ) -> str:
        """用 prompts.REFLECTION_PROMPT 构建含完整历史的 prompt。"""
        raise NotImplementedError("ReflectionLoopController._build_reflection_prompt")
