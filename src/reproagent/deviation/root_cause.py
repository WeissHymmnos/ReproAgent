"""偏差根因分类。"""

from __future__ import annotations

from reproagent.models.deviation import DeviationReport, RootCause
from reproagent.models.replication import ReplicationConfig


def classify_root_cause(
    deviation: DeviationReport,
    config: ReplicationConfig,
) -> RootCause:
    """启发式规则 + 可选 LLM。

    - IC 方向反了 → LOOKAHEAD_BIAS
    - 所有指标整体偏高/偏低 → DATA_MISMATCH
    - 部分指标匹配但 IC 差距大 → FORMULA_ERROR
    - IC 匹配但收益偏差大 → PARAMETER_ERROR
    - 规则不命中 → UNKNOWN（后续可接 LLM）
    """
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
            abs(v) <= 0.05
            for k, v in deltas.items()
            if k != "ic_mean" and k != "ic_ir"
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

    return RootCause.UNKNOWN