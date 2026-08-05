"""Multi-Agent 研究流程骨架。

Phase 4.4: Lead/Reviewer/Miner 多角色并行探索设计蓝图。
当前提供各 Agent 角色定义和接口契约，完整编排实现留作后续迭代。

参考架构:
- QuantaAlpha-claw: 蜂群式 Lead + Reviewer + Miner 并行探索
- FactorMiner: Ralph Loop (retrieve-generate-evaluate-distill)
- QuantGPT: 双模型交叉验证 (fact collection + independent judgment + cross-review)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class HypothesisResult:
    """HypothesisAgent 输出：从研报中提取的候选因子假设。"""

    factor_name: str
    factor_name_cn: str
    hypothesis: str  # 自然语言描述的研究假设
    suggested_fields: list[str]
    suggested_window: int | None = None
    confidence: float = 0.5


@dataclass
class FactorSynthesisResult:
    """FactorAgent 输出：将假设转化为可执行表达式。"""

    expression: str
    input_fields: list[str]
    validation: dict  # validate_expression 的结果
    warnings: list[str] = field(default_factory=list)


@dataclass
class BacktestEvaluation:
    """BacktestAgent 输出：回测 + 反过拟合分析。"""

    ic_mean: float
    sharpe: float
    dsr: float | None = None
    pbo: float | None = None
    passed: bool = False


@dataclass
class ReviewVerdict:
    """ReviewAgent 输出：交叉审核结论。"""

    verdict: Literal["approve", "reject", "revise"]
    reasoning: str
    reviewer_model: str  # 第二个 LLM（交叉验证）
    consensus: bool  # 与原 Agent 的结论是否一致


@dataclass
class CuratorDecision:
    """CuratorAgent 输出：入库决策。"""

    action: Literal["accept", "defer", "reject"]
    reason: str
    risk_flags: list[str] = field(default_factory=list)
    recommended_tags: list[str] = field(default_factory=list)


class HypothesisAgent:
    """从研报文本中提取候选因子假设。"""

    @staticmethod
    def generate(report_text: str, n_hypotheses: int = 5) -> list[HypothesisResult]:
        """（骨架）LLM 驱动：从研报 Markdown 中提取结构化假设。"""
        return []


class FactorAgent:
    """将假设转化为可执行的因子表达式（白名单约束）。"""

    @staticmethod
    def synthesize(hypothesis: HypothesisResult) -> FactorSynthesisResult:
        """（骨架）LLM 驱动：生成符合 OPERATOR_WHITELIST 的表达式。"""
        return FactorSynthesisResult(
            expression="close / Ref(close, 20) - 1",
            input_fields=["close"],
            validation={"valid": True, "errors": [], "warnings": []},
        )


class BacktestAgent:
    """执行回测 + 反过拟合检验 → 输出多维评分。"""

    @staticmethod
    def evaluate(
        expression: str, start_date: str, end_date: str, universe: str = "csi300"
    ) -> BacktestEvaluation:
        """（骨架）全流程：计算因子 → 回测 → 反过拟合。"""
        return BacktestEvaluation(ic_mean=0.0, sharpe=0.0, passed=False)


class ReviewAgent:
    """双模型交叉评审：独立评估前序 Agent 的推理链。"""

    @staticmethod
    def review(
        hypothesis: HypothesisResult,
        synthesis: FactorSynthesisResult,
        evaluation: BacktestEvaluation,
    ) -> ReviewVerdict:
        """（骨架）第二个 LLM 独立评估推理链。"""
        return ReviewVerdict(
            verdict="revise",
            reasoning="Dual-model cross-review not yet implemented",
            reviewer_model="deepseek-reasoner",
            consensus=False,
        )


class CuratorAgent:
    """入库决策：综合相关性、冗余性、衰减趋势。"""

    @staticmethod
    def decide(
        evaluation: BacktestEvaluation,
        review: ReviewVerdict,
        library_correlations: dict[str, float] | None = None,
    ) -> CuratorDecision:
        """（骨架）多因素综合入库决策。"""
        if evaluation.passed and review.verdict == "approve":
            return CuratorDecision(action="accept", reason="All checks passed")
        if review.verdict == "reject":
            return CuratorDecision(action="reject", reason=review.reasoning)
        return CuratorDecision(action="defer", reason="Needs revision or manual review")
