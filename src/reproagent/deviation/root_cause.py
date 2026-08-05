"""偏差根因分类：启发式规则 + 统计显著性 + LLM fallback。"""

from __future__ import annotations

import math

import numpy as np

from reproagent.models.deviation import DeviationReport, RootCause
from reproagent.models.replication import ReplicationConfig


def _bootstrap_test_significance(deviation: DeviationReport, n_boot: int = 200) -> bool:
    """用 bootstrap 判断偏差是否在统计上显著。

    对每条 metric_deviations，假设零均值的正态分布，
    bootstrap 抽样判断偏差超出抽样噪声范围。
    简化实现：偏差绝对值的均值 > 容忍区间的 2 倍视为显著。
    """
    if not deviation.metric_deviations:
        return False
    values = list(deviation.metric_deviations.values())
    if len(values) < 2:
        return abs(values[0]) > 0.02
    mean_abs = np.mean([abs(v) for v in values])
    std_abs = np.std([abs(v) for v in values])
    if std_abs < 1e-10:
        return mean_abs > 0.02
    # t-test 近似
    t_stat = mean_abs / (std_abs / math.sqrt(len(values)))
    # df = n-1, 双尾 α=0.05 的临界值 ≈ 2
    return t_stat > 2.0


def classify_root_cause(
    deviation: DeviationReport,
    config: ReplicationConfig,
    *,
    use_llm_fallback: bool = True,
) -> RootCause:
    """启发式规则 + 可选 LLM fallback。

    - IC 方向反了 → LOOKAHEAD_BIAS
    - 所有指标整体偏高/偏低 → DATA_MISMATCH
    - 部分指标匹配但 IC 差距大 → FORMULA_ERROR
    - IC 匹配但收益偏差大 → PARAMETER_ERROR
    - 规则不命中 + 统计显著 → LLM fallback
    - 规则不命中 + 不显著 → UNKNOWN
    """
    md = deviation.metric_deviations
    if not md:
        return RootCause.UNKNOWN

    ic_delta = md.get("ic_mean")
    icir_delta = md.get("ic_ir")
    sharpe_delta = md.get("sharpe_ratio")
    ls_delta = md.get("long_short_annual_return")
    mdd_delta = md.get("max_drawdown")

    # -- 规则分类（与之前逻辑保持一致）--
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

    # -- UNKNOWN 时尝试 LLM fallback --
    is_significant = _bootstrap_test_significance(deviation)
    if is_significant and use_llm_fallback:
        return _llm_classify_root_cause(deviation, config)

    return RootCause.UNKNOWN


def _llm_classify_root_cause(
    deviation: DeviationReport,
    config: ReplicationConfig,
) -> RootCause:
    """使用 LLM 分析偏差模式并分类根因。

    当前为骨架实现：规则不命中时返回 UNKNOWN，
    并在 detail 中标记为待 LLM 分析。
    完整的 LLM prompt 调用留作后续迭代接入。
    """
    deviation.root_cause_detail = (
        "Rule-based classification returned UNKNOWN with significant deviation "
        f"(metrics: {deviation.metric_deviations}). LLM fallback not yet wired."
    )
    return RootCause.UNKNOWN
