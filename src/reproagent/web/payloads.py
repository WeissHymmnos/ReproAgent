"""Pure JSON payload builders for the browser workstation (testable without HTTP)."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from reproagent.library.manager import FactorLibraryManager
from reproagent.models.library import FactorLibraryEntry, LibraryFilter
from reproagent.persistence.repository import Repository
from reproagent.persistence.tables import ManualReviewQueueTable


def _entry_to_dict(entry: FactorLibraryEntry) -> dict[str, Any]:
    f = entry.factor
    return {
        "id": entry.id,
        "name": f.name,
        "name_cn": f.name_cn or f.name,
        "style": str(f.style) if f.style else "other",
        "status": entry.status,
        "version": entry.version,
        "formula": f.formula,
        "input_fields": list(f.input_fields or []),
        "universe": f.universe,
        "rebalance_frequency": f.rebalance_frequency,
        "report_id": entry.report_id,
        "deviation_passed": bool(entry.deviation_passed),
        "tags": list(entry.tags or []),
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "dedup_hash": entry.dedup_hash,
        "backtest_result_id": entry.backtest_result_id,
        "metrics": dict(getattr(entry, "metrics", None) or {}),
    }


def build_library_list(
    manager: FactorLibraryManager,
    *,
    style: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return factor library list from the real FactorLibraryManager."""
    filt: LibraryFilter | None = None
    if style or status:
        filt = LibraryFilter(style=style, status=status)
    entries = manager.list(filt, query=query, limit=limit)
    items = [_entry_to_dict(e) for e in entries]
    return {
        "items": items,
        "count": len(items),
        "empty": len(items) == 0,
    }


def build_library_detail(
    manager: FactorLibraryManager,
    factor_id: str,
) -> dict[str, Any] | None:
    """Return one library entry or None if missing."""
    entry = manager.get(factor_id)
    if entry is None:
        return None
    return _entry_to_dict(entry)


def build_review_list(repo: Repository, *, limit: int | None = None) -> dict[str, Any]:
    """List pending manual-review queue items from the real repository."""
    with Session(repo.engine) as session:
        rows = session.exec(
            select(ManualReviewQueueTable)
            .where(ManualReviewQueueTable.status == "pending")
            .order_by(ManualReviewQueueTable.created_at)
        ).all()

    total = len(rows)
    if limit is not None:
        rows = rows[: max(0, int(limit))]

    items: list[dict[str, Any]] = []
    for row in rows:
        report = repo.get_report(row.report_id)
        items.append(
            {
                "entry_id": row.id,
                "report_id": row.report_id,
                "reason": row.reason,
                "status": row.status,
                "created_at": row.created_at,
                "title": report.title if report else None,
                "broker": report.broker if report else None,
                "file_path": str(report.file_path) if report and report.file_path else None,
                "validation_status": report.validation_status if report else None,
            }
        )
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "empty": total == 0,
    }


def build_summary(manager: FactorLibraryManager, repo: Repository) -> dict[str, Any]:
    """Dashboard summary counts from real library + review state."""
    from sqlalchemy import func, text

    from reproagent.persistence.tables import FactorLibraryTable

    styles: dict[str, int] = {}
    library_count = 0
    pending_n = 0
    with Session(repo.engine) as session:
        pending = session.exec(
            select(func.count())
            .select_from(ManualReviewQueueTable)
            .where(ManualReviewQueueTable.status == "pending")
        ).one()
        pending_n = int(pending or 0)
        library_count = int(
            session.exec(select(func.count()).select_from(FactorLibraryTable)).one() or 0
        )
        try:
            rows = session.execute(
                text(
                    "SELECT COALESCE(json_extract(factor_json, '$.style'), 'other') "
                    "AS style, COUNT(*) FROM factor_library GROUP BY 1"
                )
            ).all()
            for style, n in rows:
                styles[str(style or "other")] = int(n)
        except Exception:  # noqa: BLE001
            styles = {}
    if not styles and library_count:
        for entry in manager.list():
            key = str(entry.factor.style or "other")
            styles[key] = styles.get(key, 0) + 1
    return {
        "library_count": library_count,
        "review_pending": pending_n,
        "styles": styles,
        "product": "ReproAgent",
        "tagline": "研报 → 因子复现 → 因子库",
    }
