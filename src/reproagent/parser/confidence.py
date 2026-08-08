"""提取置信度与数据字典 WARN 门控。"""

from __future__ import annotations

from dataclasses import dataclass

from reproagent.models.factor_spec import ParsedFactorSpec

# 低于此置信度：默认进人工复核，不自动入库
LOW_CONFIDENCE_THRESHOLD = 0.5
# 数据字典 WARN 占比超过此值：复核
WARN_RATIO_THRESHOLD = 0.5


@dataclass
class ConfidenceGateResult:
    """单因子置信度门控结果。"""

    ok: bool
    reasons: list[str]
    extraction_confidence: float
    warn_mapping_count: int
    total_mappings: int


def evaluate_confidence(
    spec: ParsedFactorSpec,
    *,
    min_confidence: float = LOW_CONFIDENCE_THRESHOLD,
    max_warn_ratio: float = WARN_RATIO_THRESHOLD,
) -> ConfidenceGateResult:
    """判断因子是否可进入自动复现/入库路径。"""
    reasons: list[str] = []
    conf = float(spec.extraction_confidence or 0.0)
    mappings = list(spec.data_dict_mappings or [])
    warns = [m for m in mappings if getattr(m, "tag", None) == "WARN"]
    warn_n = len(warns)
    total = len(mappings)

    if conf < min_confidence:
        reasons.append(f"low_extraction_confidence={conf:.2f}<{min_confidence}")

    if total > 0 and (warn_n / total) > max_warn_ratio:
        reasons.append(f"warn_mapping_ratio={warn_n}/{total}>{max_warn_ratio}")

    # 描述中的 [WARN] 标记（schema_validator 注入）
    if "[WARN]" in (spec.description or ""):
        reasons.append("description_contains_WARN")

    if not (spec.formula or "").strip():
        reasons.append("empty_formula")

    return ConfidenceGateResult(
        ok=len(reasons) == 0,
        reasons=reasons,
        extraction_confidence=conf,
        warn_mapping_count=warn_n,
        total_mappings=total,
    )
