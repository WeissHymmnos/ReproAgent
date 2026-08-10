"""RMA-lite：研报知识吸收（A 可行性 + B 机制族 + C archetype 线索）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.memory import (
    EligibilityDecision,
    MechanismFamily,
    ReportKnowledgeAtom,
    ResearchArchetype,
)
from reproagent.settings import Settings

# 本地 / 多数行情后端默认可提供的字段类型
_OHLCV_TYPES = frozenset({"price", "volume", "derived"})
# 需要基本面/宏观数据源的类型
_FUNDAMENTAL_TYPES = frozenset({"fundamental", "macro"})

_FAMILY_KEYWORDS: list[tuple[MechanismFamily, tuple[str, ...]]] = [
    (MechanismFamily.MOMENTUM, ("mom", "动量", "momentum", "趋势", "continuation")),
    (MechanismFamily.REVERSAL, ("rev", "反转", "reversal", "mean reversion", "均值回复")),
    (MechanismFamily.VALUE, ("value", "估值", "pe", "pb", "ps", "估值类")),
    (MechanismFamily.GROWTH, ("growth", "成长", "营收增长")),
    (MechanismFamily.QUALITY, ("quality", "质量", "roe", "roa")),
    (MechanismFamily.SIZE, ("size", "市值", "小盘")),
    (MechanismFamily.VOLATILITY, ("vol", "波动", "volatility", "振幅")),
    (MechanismFamily.LIQUIDITY, ("liq", "流动性", "换手", "turnover", "illiquid")),
    (MechanismFamily.PRICE_VOLUME, ("量价", "price.volume", "价量", "volume.price")),
    (MechanismFamily.MACRO, ("macro", "宏观", "利率", "industry")),
    (MechanismFamily.TECHNICAL, ("technical", "技术", "rsi", "macd", "boll")),
]


def infer_mechanism_family(spec: ParsedFactorSpec) -> MechanismFamily:
    """规则推断 B-layer 机制族。"""
    blob = " ".join(
        [
            spec.factor_name,
            spec.factor_name_cn,
            spec.description or "",
            spec.formula or "",
        ]
    ).lower()
    for family, keys in _FAMILY_KEYWORDS:
        if any(k.lower() in blob for k in keys):
            return family
    return MechanismFamily.OTHER


def assess_eligibility(
    spec: ParsedFactorSpec,
    settings: Settings,
) -> tuple[EligibilityDecision, str]:
    """A-layer：对照当前 DATA_SOURCE 判断是否可进入复现。

    - local / ricequant / qlib / tushare：默认支持 price/volume/derived
    - 依赖 fundamental/macro 且数据源未显式支持 → DROP
    """
    needed = {f.data_type for f in (spec.input_fields or [])}
    hard = needed & _FUNDAMENTAL_TYPES
    if hard and settings.data_source == "local":
        return (
            EligibilityDecision.DROP,
            f"local data cannot provide fields of types {sorted(hard)}; "
            "need fundamental/macro backend or remap inputs",
        )
    # 无 input_fields 时保守 KEEP（由回测再暴露问题）
    if not needed:
        return EligibilityDecision.KEEP, "no typed inputs; defer to backtest"
    only_ok = needed <= _OHLCV_TYPES
    if only_ok:
        return EligibilityDecision.KEEP, "inputs expressible under OHLCV-like contract"
    if hard and settings.data_source in ("ricequant", "tushare", "qlib"):
        return (
            EligibilityDecision.KEEP,
            f"fundamental/macro types {sorted(hard)} assumed available via {settings.data_source}",
        )
    return (
        EligibilityDecision.KEEP,
        f"mixed input types {sorted(needed)}; proceed with caution",
    )


def build_knowledge_atom(
    spec: ParsedFactorSpec,
    report_id: str,
    settings: Settings,
    *,
    archetype_id: str | None = None,
) -> ReportKnowledgeAtom:
    """从因子规格构建一条 knowledge atom。"""
    decision, reason = assess_eligibility(spec, settings)
    family = infer_mechanism_family(spec)
    return ReportKnowledgeAtom(
        id=uuid4().hex,
        report_id=report_id,
        chunk_text=(spec.description or spec.formula or spec.factor_name)[:2000],
        source_pages=list(spec.source_pages or []),
        a_decision=decision,
        a_reason=reason,
        mechanism_family=family,
        research_path=f"{family.value}:{spec.factor_name}",
        archetype_id=archetype_id,
        factor_spec_id=spec.id,
        extra={
            "factor_name": spec.factor_name,
            "formula": spec.formula,
            "input_types": [f.data_type for f in (spec.input_fields or [])],
        },
        created_at=datetime.now(UTC),
    )


def ensure_archetype(
    family: MechanismFamily,
    role: str,
    report_id: str,
    research_path: str,
    existing: ResearchArchetype | None = None,
) -> ResearchArchetype:
    """创建或更新 C-layer archetype 线索。"""
    now = datetime.now(UTC)
    if existing is not None:
        paths = list(dict.fromkeys([*existing.report_grounded_paths, research_path]))
        reports = list(dict.fromkeys([*existing.source_report_ids, report_id]))
        return existing.model_copy(
            update={
                "report_grounded_paths": paths,
                "source_report_ids": reports,
                "updated_at": now,
            }
        )
    return ResearchArchetype(
        id=f"arch-{family.value}-{uuid4().hex[:8]}",
        family=family,
        role=role or f"{family.value} research cue",
        report_grounded_paths=[research_path] if research_path else [],
        source_report_ids=[report_id],
        notes="RMA-lite auto archetype",
        created_at=now,
        updated_at=now,
    )


def archetype_id_for_family(family: MechanismFamily) -> str:
    """稳定的默认 archetype id（按族聚合，便于检索）。"""
    return f"arch-{family.value}-default"
