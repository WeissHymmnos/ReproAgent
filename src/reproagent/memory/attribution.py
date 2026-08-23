"""FAA-lite：按最终机制重贴 B/C 标签。"""

from __future__ import annotations

from reproagent.memory.rma import archetype_id_for_family, infer_mechanism_family
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.memory import MechanismFamily

_STYLE_TO_FAMILY: dict[str, MechanismFamily] = {
    "momentum": MechanismFamily.MOMENTUM,
    "value": MechanismFamily.VALUE,
    "growth": MechanismFamily.GROWTH,
    "quality": MechanismFamily.QUALITY,
    "size": MechanismFamily.SIZE,
    "volatility": MechanismFamily.VOLATILITY,
    "liquidity": MechanismFamily.LIQUIDITY,
    "macro": MechanismFamily.MACRO,
    "technical": MechanismFamily.TECHNICAL,
    "other": MechanismFamily.OTHER,
}


def attribute_from_spec(spec: ParsedFactorSpec) -> tuple[MechanismFamily, str]:
    """从 ParsedFactorSpec 归因 → (family, archetype_id)。"""
    family = infer_mechanism_family(spec)
    return family, archetype_id_for_family(family)


def attribute_from_factor_def(factor: FactorDefinition) -> tuple[MechanismFamily, str]:
    """从 FactorDefinition 归因（入库后）。"""
    style = (factor.style or "other").lower()
    family = _STYLE_TO_FAMILY.get(style, MechanismFamily.OTHER)
    # 若 style=other，再扫 name/formula
    if family == MechanismFamily.OTHER:
        pseudo = ParsedFactorSpec(
            id=factor.id,
            factor_name=factor.name,
            factor_name_cn=factor.name_cn,
            description="",
            formula=factor.formula,
            input_fields=[],
            computation_steps=[],
            extraction_confidence=0.0,
        )
        family = infer_mechanism_family(pseudo)
    return family, archetype_id_for_family(family)


def elite_worthy(
    *,
    deviation_passed: bool,
    metric_deviations: dict[str, float] | None = None,
    max_abs_ic_delta: float = 0.015,
) -> bool:
    """简单 elite 门槛：通过偏差且 IC 偏差足够小（若有）。"""
    if not deviation_passed:
        return False
    if not metric_deviations:
        return True
    ic = metric_deviations.get("ic_mean")
    if ic is None:
        return True
    return abs(ic) <= max_abs_ic_delta
