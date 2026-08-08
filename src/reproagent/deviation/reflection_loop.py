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
    """有界反思循环：max_iterations=3，连续 2 次无改善则 escalate。

    集成跨报告经验记忆（ExperienceMemory），在反思 prompt 中注入
    历史成功/失败模式；修订时按 root_cause 选择策略。
    """

    def __init__(
        self,
        reproducer: FactorReproducerProtocol,
        analyzer: DeviationAnalyzerProtocol,
        llm_extractor: LLMExtractor,
        config_builder: ConfigBuilder,
        tolerances: ToleranceConfig,
        repository: Repository,
        experience_memory: object | None = None,
        max_iterations: int = 3,
    ) -> None:
        self.reproducer = reproducer
        self.analyzer = analyzer
        self.llm_extractor = llm_extractor
        self.config_builder = config_builder
        self.tolerances = tolerances
        self.repository = repository
        self.experience_memory = experience_memory
        self.max_iterations = max_iterations

    def run(
        self,
        initial_config: ReplicationConfig,
        reported: ReportedMetrics,
    ) -> ReflectionState:
        import uuid
        from datetime import UTC, datetime

        from reproagent.exceptions import PersistenceError
        from reproagent.models.reflection import ReflectionStep

        state = ReflectionState(
            id=uuid.uuid4().hex,
            factor_id=initial_config.factor_specs[0].id,
            report_id=initial_config.report_id,
            original_config=initial_config,
            max_iterations=self.max_iterations,
            current_iteration=0,
            status="in_progress",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.repository.save_reflection_state(state)

        current_config = initial_config

        while state.current_iteration < state.max_iterations and state.status == "in_progress":
            result = self.reproducer.reproduce(current_config)

            deviation = self.analyzer.analyze(result, reported, self.tolerances)
            deviation.root_cause = self.analyzer.classify_root_cause(deviation, current_config)

            score = self._deviation_score(deviation)

            if deviation.passed:
                state.status = "converged"

            step = ReflectionStep(
                id=uuid.uuid4().hex,
                state_id=state.id,
                iteration=state.current_iteration,
                prompt=(
                    self._build_reflection_prompt(state, deviation)
                    if state.current_iteration > 0
                    else ""
                ),
                response="",
                revised_config=current_config,
                deviation_report=deviation,
                created_at=datetime.now(UTC),
            )

            if state.best_deviation_score is None or score < state.best_deviation_score:
                state.best_deviation_score = score
                state.best_step_id = step.id
            else:
                no_improvement_streak = 0
                for s in reversed(state.steps):
                    if s.deviation_report:
                        s_score = self._deviation_score(s.deviation_report)
                        if s_score >= state.best_deviation_score:
                            no_improvement_streak += 1
                        else:
                            break
                if no_improvement_streak >= 1:
                    state.status = "escalated"

            self.repository.save_reflection_step(step)
            reloaded = self.repository.get_reflection_state(state.id)
            if reloaded is None:
                raise PersistenceError(
                    f"reflection state {state.id} disappeared after save_reflection_step"
                )
            state = reloaded

            if state.status in ("converged", "escalated"):
                break

            prompt = self._build_reflection_prompt(state, deviation)
            cause = (
                deviation.root_cause.value
                if hasattr(deviation.root_cause, "value")
                else str(deviation.root_cause)
            )
            revised_spec = self.llm_extractor.revise(
                prompt,
                current_config.factor_specs[0],
                root_cause=cause,
            )

            current_config = current_config.model_copy(deep=True)
            current_config.factor_specs = [revised_spec]

            state.current_iteration += 1
            self.repository.save_reflection_state(state)

        if state.status == "in_progress":
            state.status = "exhausted"
            self.repository.save_reflection_state(state)

        return state

    def _deviation_score(self, deviation: DeviationReport) -> float:
        import math

        if deviation.passed:
            return 0.0
        if not deviation.metric_deviations:
            return 1.0

        sum_sq = 0.0
        for k, v in deviation.metric_deviations.items():
            if k == "ic_mean":
                tol = self.tolerances.ic_mean_abs
            elif k == "ic_ir":
                tol = self.tolerances.ic_ir_abs
            elif k == "long_short_annual_return":
                tol = self.tolerances.long_short_return_rel
                if tol == 0:
                    tol = 5.0
            elif k == "sharpe_ratio":
                tol = self.tolerances.sharpe_abs
            elif k == "max_drawdown":
                tol = self.tolerances.max_drawdown_abs
            else:
                tol = 1.0
            sum_sq += (v / tol) ** 2
        return math.sqrt(sum_sq)

    def _build_reflection_prompt(
        self,
        state: ReflectionState,
        latest_deviation: DeviationReport,
    ) -> str:
        from reproagent.parser.prompts import REFLECTION_PROMPT

        experience_context = ""
        if self.experience_memory is not None:
            try:
                spec0 = state.original_config.factor_specs[0]
                fields = [f.name for f in (spec0.input_fields or [])]
                experience_context = self.experience_memory.build_reflection_context(
                    spec0.formula, fields
                )
            except Exception:  # noqa: BLE001
                experience_context = ""

        return REFLECTION_PROMPT.render(
            original_spec=state.original_config.factor_specs[0],
            history=state.steps,
            latest_deviation=latest_deviation,
            experience_context=experience_context,
        )
