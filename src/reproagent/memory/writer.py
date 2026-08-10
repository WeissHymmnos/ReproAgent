"""记忆写入：pipeline / review 统一出口。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from reproagent.memory.attribution import attribute_from_spec
from reproagent.memory.rma import (
    archetype_id_for_family,
    assess_eligibility,
    build_knowledge_atom,
    ensure_archetype,
    infer_mechanism_family,
)
from reproagent.memory.store import MemoryStore
from reproagent.models.factor_spec import ParsedFactorSpec
from reproagent.models.memory import (
    EligibilityDecision,
    FeedbackKind,
    FeedbackRecord,
    FeedbackSource,
    MechanismFamily,
)
from reproagent.settings import Settings


class MemoryWriter:
    """封装 RMA 吸收 + GOOD/BAD 反馈写入。"""

    def __init__(self, store: MemoryStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def absorb_specs(
        self,
        specs: list[ParsedFactorSpec],
        report_id: str,
    ) -> list[dict[str, Any]]:
        """对每个 factor spec 做 RMA-lite 吸收，返回摘要列表。"""
        summaries: list[dict[str, Any]] = []
        for spec in specs:
            family = infer_mechanism_family(spec)
            arch_id = archetype_id_for_family(family)
            existing = self.store.get_archetype(arch_id)
            arch = ensure_archetype(
                family,
                role=f"{family.value} default",
                report_id=report_id,
                research_path=f"{family.value}:{spec.factor_name}",
                existing=existing,
            )
            # 稳定 id 覆盖
            arch = arch.model_copy(update={"id": arch_id})
            self.store.save_archetype(arch)

            atom = build_knowledge_atom(
                spec, report_id, self.settings, archetype_id=arch_id
            )
            self.store.save_knowledge(atom)
            summaries.append(
                {
                    "factor_name": spec.factor_name,
                    "a_decision": str(atom.a_decision),
                    "a_reason": atom.a_reason,
                    "mechanism_family": str(family),
                    "archetype_id": arch_id,
                    "knowledge_id": atom.id,
                }
            )
        return summaries

    def is_feasible(self, spec: ParsedFactorSpec) -> tuple[bool, str]:
        decision, reason = assess_eligibility(spec, self.settings)
        return decision == EligibilityDecision.KEEP, reason

    def write_good(
        self,
        *,
        report_id: str,
        spec: ParsedFactorSpec,
        factor_id: str | None,
        metrics_summary: dict[str, Any] | None = None,
        principle: str | None = None,
        source: FeedbackSource = FeedbackSource.REAL,
        source_run_id: str | None = None,
    ) -> FeedbackRecord:
        family, arch_id = attribute_from_spec(spec)
        rec = FeedbackRecord(
            id=uuid4().hex,
            kind=FeedbackKind.GOOD,
            report_id=report_id,
            factor_name=spec.factor_name,
            factor_id=factor_id,
            mechanism_family=family,
            archetype_id=arch_id,
            principle=principle
            or f"Reproduced {spec.factor_name} within tolerance under family {family.value}",
            metrics_summary=metrics_summary or {},
            source_run_id=source_run_id,
            source=source,
            tags=["pipeline"],
            created_at=datetime.now(UTC),
        )
        return self.store.save_feedback(rec)

    def write_bad(
        self,
        *,
        report_id: str,
        spec: ParsedFactorSpec | None,
        factor_name: str,
        failure_type: str,
        root_cause: str | None = None,
        avoid_rule: str | None = None,
        repair_hint: str | None = None,
        metrics_summary: dict[str, Any] | None = None,
        source: FeedbackSource = FeedbackSource.REAL,
        source_run_id: str | None = None,
        mechanism_family: MechanismFamily | None = None,
    ) -> FeedbackRecord:
        if spec is not None:
            family, arch_id = attribute_from_spec(spec)
            name = spec.factor_name
        else:
            family = mechanism_family or MechanismFamily.OTHER
            arch_id = archetype_id_for_family(family)
            name = factor_name
        rec = FeedbackRecord(
            id=uuid4().hex,
            kind=FeedbackKind.BAD,
            report_id=report_id,
            factor_name=name,
            mechanism_family=family,
            archetype_id=arch_id,
            failure_type=failure_type,
            root_cause=root_cause,
            avoid_rule=avoid_rule
            or f"Avoid repeating failure_type={failure_type} for {name}",
            repair_hint=repair_hint,
            metrics_summary=metrics_summary or {},
            source_run_id=source_run_id,
            source=source,
            tags=["pipeline"],
            created_at=datetime.now(UTC),
        )
        return self.store.save_feedback(rec)

    def write_human_decision(
        self,
        *,
        report_id: str | None,
        factor_name: str | None,
        decision: str,
        reason: str,
        failure_type: str | None = None,
    ) -> FeedbackRecord:
        kind = FeedbackKind.GOOD if decision == "approve" else FeedbackKind.BAD
        rec = FeedbackRecord(
            id=uuid4().hex,
            kind=kind,
            report_id=report_id,
            factor_name=factor_name,
            failure_type=failure_type or f"human_{decision}",
            avoid_rule=None if kind == FeedbackKind.GOOD else reason,
            principle=reason if kind == FeedbackKind.GOOD else None,
            repair_hint=None if kind == FeedbackKind.GOOD else reason,
            source=FeedbackSource.HUMAN,
            tags=["human_review"],
            created_at=datetime.now(UTC),
        )
        return self.store.save_feedback(rec)
