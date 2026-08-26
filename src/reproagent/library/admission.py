"""入库门：反过拟合 + 冗余。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import polars as pl

from reproagent.models.library import FactorLibraryEntry


@dataclass
class AdmissionDecision:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    overfit: bool = False
    redundant: bool = False
    anti: dict[str, Any] = field(default_factory=dict)
    redundancy: dict[str, Any] = field(default_factory=dict)


def evaluate_admission(
    manager: Any,
    *,
    factor_values: pl.DataFrame | None = None,
    backtest: Any | None = None,
    max_correlation: float = 0.7,
    min_obs_for_overfit: int = 20,
) -> AdmissionDecision:
    anti: dict[str, Any] = {}
    if backtest is not None:
        from reproagent.reproducer.overfit_eval import evaluate_from_equity

        path = getattr(backtest, "equity_curve_path", None)
        anti = evaluate_from_equity(str(path) if path is not None else None)
        pbo = anti.get("pbo")
        n_obs = int(anti.get("n_obs") or 0)
        overfit = bool(
            n_obs >= min_obs_for_overfit
            and (
                bool(anti.get("pbo_overfit"))
                or (pbo is not None and float(pbo) > 0.5)
                or bool(anti.get("dsr_deflated"))
            )
        )
    else:
        overfit = False

    redundancy = {
        "is_redundant": False,
        "max_correlation": 0.0,
        "most_similar_factor_id": None,
    }
    if factor_values is not None and manager is not None:
        redundancy = manager.check_redundancy(factor_values, max_correlation=max_correlation)
    redundant = bool(redundancy.get("is_redundant"))

    reasons: list[str] = []
    if redundant:
        reasons.append("redundant")
    if overfit:
        reasons.append("overfit")
    n_obs = int(anti.get("n_obs") or 0)
    accepted = not redundant
    if overfit and n_obs >= 60:
        accepted = False
    return AdmissionDecision(
        accepted=accepted,
        reasons=reasons,
        overfit=overfit,
        redundant=redundant,
        anti=anti,
        redundancy=redundancy,
    )


def annotate_entry(entry: FactorLibraryEntry, decision: AdmissionDecision) -> FactorLibraryEntry:
    metrics = dict(entry.metrics or {})
    if decision.anti:
        metrics["anti_overfitting"] = {
            k: decision.anti.get(k)
            for k in ("dsr", "pbo", "min_btl", "dsr_pvalue", "placebo_pvalue", "n_obs")
        }
    if decision.redundancy:
        metrics["redundancy"] = {
            "is_redundant": decision.redundant,
            "max_correlation": decision.redundancy.get("max_correlation"),
            "most_similar_factor_id": decision.redundancy.get("most_similar_factor_id"),
        }
    tags = list(entry.tags or [])
    if decision.redundant and "redundant" not in tags:
        tags.append("redundant")
    if decision.overfit and "overfit" not in tags:
        tags.append("overfit")
    status = "review" if not decision.accepted else entry.status
    return entry.model_copy(update={"metrics": metrics, "tags": tags, "status": status})


def gate_register(
    manager: Any,
    entry: FactorLibraryEntry,
    *,
    factor_values: pl.DataFrame | None = None,
    backtest: Any | None = None,
    check_redundancy: bool = True,
) -> tuple[FactorLibraryEntry, AdmissionDecision]:
    """过门后入库。未通过的仍写入，``status=review``，打 ``redundant`` / ``overfit``。"""
    decision = AdmissionDecision(accepted=True)
    if check_redundancy or backtest is not None:
        decision = evaluate_admission(
            manager,
            factor_values=factor_values if check_redundancy else None,
            backtest=backtest,
        )
    updated = annotate_entry(entry, decision)
    saved = manager.register(
        updated, check_redundancy=False, factor_values=None, backtest=None
    )
    return saved, decision

