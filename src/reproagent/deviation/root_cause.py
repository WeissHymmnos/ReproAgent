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
    raise NotImplementedError("deviation.root_cause.classify_root_cause")
