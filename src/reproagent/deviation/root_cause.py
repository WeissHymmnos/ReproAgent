"""偏差根因分类：启发式规则 + 统计显著性 + LLM fallback。"""

from __future__ import annotations

import logging
import math
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from reproagent.models.deviation import DeviationReport, RootCause
from reproagent.models.replication import ReplicationConfig

logger = logging.getLogger(__name__)


class RootCauseLLMAnswer(BaseModel):
    """LLM 根因分类结构化输出。"""

    root_cause: Literal[
        "DATA_MISMATCH",
        "FORMULA_ERROR",
        "PARAMETER_ERROR",
        "UNIVERSE_MISMATCH",
        "LOOKAHEAD_BIAS",
        "UNKNOWN",
    ] = "UNKNOWN"
    reasoning: str = Field(default="", description="简短理由")


def _bootstrap_test_significance(deviation: DeviationReport, n_boot: int = 200) -> bool:
    """用 bootstrap 判断偏差是否在统计上显著。"""
    del n_boot  # 简化实现不使用显式 bootstrap 抽样次数
    if not deviation.metric_deviations:
        return False
    values = list(deviation.metric_deviations.values())
    if len(values) < 2:
        return bool(abs(values[0]) > 0.02)
    mean_abs = np.mean([abs(v) for v in values])
    std_abs = np.std([abs(v) for v in values])
    if std_abs < 1e-10:
        return bool(mean_abs > 0.02)
    t_stat = mean_abs / (std_abs / math.sqrt(len(values)))
    return bool(t_stat > 2.0)


def classify_root_cause(
    deviation: DeviationReport,
    config: ReplicationConfig,
    *,
    use_llm_fallback: bool = True,
) -> RootCause:
    """启发式规则 + 可选 LLM fallback。"""
    md = deviation.metric_deviations
    if not md:
        return RootCause.UNKNOWN

    ic_delta = md.get("ic_mean")
    icir_delta = md.get("ic_ir")
    sharpe_delta = md.get("sharpe_ratio")
    ls_delta = md.get("long_short_annual_return")
    mdd_delta = md.get("max_drawdown")

    if ic_delta is not None and abs(ic_delta) > 0.05:
        if icir_delta is not None and abs(icir_delta) > 0.3 and (ic_delta * icir_delta) > 0:
            return RootCause.LOOKAHEAD_BIAS

    deltas = {
        k: v
        for k, v in [
            ("ic_mean", ic_delta),
            ("ic_ir", icir_delta),
            ("sharpe_ratio", sharpe_delta),
            ("long_short_annual_return", ls_delta),
            ("max_drawdown", mdd_delta),
        ]
        if v is not None
    }

    if not deltas:
        return RootCause.UNKNOWN

    signs = [1 if v > 0 else -1 for v in deltas.values() if abs(v) > 0.01]
    if signs and len(set(signs)) == 1 and len(signs) >= 3:
        return RootCause.DATA_MISMATCH

    ic_ok = ic_delta is not None and abs(ic_delta) <= 0.03
    if ic_ok and (
        (sharpe_delta is not None and abs(sharpe_delta) > 0.3)
        or (ls_delta is not None and abs(ls_delta) > 5.0)
    ):
        return RootCause.PARAMETER_ERROR

    if ic_delta is not None and abs(ic_delta) > 0.03:
        others_ok = any(
            abs(v) <= 0.05 for k, v in deltas.items() if k != "ic_mean" and k != "ic_ir"
        )
        if others_ok:
            return RootCause.FORMULA_ERROR

    if (
        ic_delta is not None
        and abs(ic_delta) > 0.02
        and sharpe_delta is not None
        and abs(sharpe_delta) > 0.2
        and (ic_delta * sharpe_delta) > 0
    ):
        return RootCause.UNIVERSE_MISMATCH

    is_significant = _bootstrap_test_significance(deviation)
    if is_significant and use_llm_fallback:
        return _llm_classify_root_cause(deviation, config)

    return RootCause.UNKNOWN


def _llm_classify_root_cause(
    deviation: DeviationReport,
    config: ReplicationConfig,
) -> RootCause:
    """使用 LLM（instructor）分析偏差模式并分类根因。

    无 API key 或调用失败时返回 UNKNOWN，并写入 root_cause_detail。
    """
    formula = ""
    universe = ""
    if config.factor_specs:
        formula = config.factor_specs[0].formula or ""
        universe = config.factor_specs[0].universe or ""

    try:
        from reproagent.settings import get_settings

        settings = get_settings()
        api_key = settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            deviation.root_cause_detail = (
                "LLM fallback skipped (no API key); metrics significant: "
                f"{deviation.metric_deviations}"
            )
            return RootCause.UNKNOWN

        try:
            import instructor
        except ImportError:
            deviation.root_cause_detail = (
                "LLM fallback skipped (instructor not installed); "
                f"metrics: {deviation.metric_deviations}"
            )
            return RootCause.UNKNOWN

        from anthropic import Anthropic
        from openai import OpenAI

        from reproagent.parser.prompts import ROOT_CAUSE_PROMPT

        prompt = ROOT_CAUSE_PROMPT.render(
            formula=formula,
            universe=universe,
            deviations=deviation.metric_deviations,
            detail=deviation.root_cause_detail or "",
        )

        if settings.llm_provider == "openai":
            client = instructor.from_openai(
                OpenAI(api_key=api_key, base_url=settings.llm_base_url)
            )
            answer = client.chat.completions.create(
                model=settings.llm_model,
                response_model=RootCauseLLMAnswer,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                seed=settings.llm_seed,
            )
        else:
            client = instructor.from_anthropic(Anthropic(api_key=api_key))
            answer = client.messages.create(
                model=settings.llm_model,
                response_model=RootCauseLLMAnswer,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )

        cause_str = answer.root_cause
        deviation.root_cause_detail = (
            f"LLM classified as {cause_str}: {answer.reasoning}"
        ).strip()
        try:
            return RootCause(cause_str)
        except ValueError:
            return RootCause.UNKNOWN
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM root-cause classification failed: %s", exc)
        deviation.root_cause_detail = (
            f"LLM fallback failed ({exc}); metrics: {deviation.metric_deviations}"
        )
        return RootCause.UNKNOWN
