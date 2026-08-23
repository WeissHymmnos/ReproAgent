"""FAA-lite：按最终机制重贴 B/C 标签。"""

from __future__ import annotations

from reproagent.memory.rma import archetype_id_for_family, infer_mechanism_family
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




