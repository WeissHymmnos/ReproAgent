"""Memory co-residency matrix and helpers.

Enforces strict memory limits so the pipeline never loads multiple heavy
models simultaneously on a 16 GB RAM machine.

Co-residency matrix (see README §Memory Co-residency Matrix):

    | Page Class              | Allowed in RAM                    | Workers |
    |-------------------------|------------------------------------|---------|
    | Text-only / light OCR   | PyMuPDF + PP-OCRv6_small           | 2       |
    | Table structure         | PyMuPDF + PP-StructureV3           | 1       |
    | VLM chart/flow          | PyMuPDF + llama-server sidecar     | 2 (shared) |
    | MinerU table            | MinerU subprocess                  | 1       |

``recommended_workers`` and ``enforce_memory_matrix`` are the single source
of truth for worker counts — the orchestrator and batch runner both import
from here to avoid duplication.
"""

from __future__ import annotations

import gc
import logging

from finreportparser.types import PageClass

logger = logging.getLogger(__name__)

_WORKERS_DEFAULT: dict[PageClass, int] = {
    PageClass.BLANK: 2,
    PageClass.TEXT_RICH: 2,
    PageClass.SCANNED: 2,
    PageClass.TABLE_CANDIDATE: 1,
    PageClass.CHART_CANDIDATE: 2,
    PageClass.MIXED: 1,
}

_WORKERS_MINERU: dict[PageClass, int] = {
    pc: 1 for pc in PageClass
}


def recommended_workers(
    page_class: PageClass | str,
    max_workers: int = 2,
    *,
    table_backend: str = "paddle",
) -> int:
    """Return the safe worker count for *page_class*.

    Parameters
    ----------
    page_class:
        The :class:`~finreportparser.types.PageClass` (or its string value).
    max_workers:
        Upper bound from user config (``Config.workers``).  The returned
        value will never exceed this.
    table_backend:
        ``"paddle"`` (default) or ``"mineru"``.  MinerU forces 1 worker
        regardless of page class.
    """
    if isinstance(page_class, str):
        page_class = PageClass(page_class)

    if table_backend == "mineru":
        base = _WORKERS_MINERU.get(page_class, 1)
    else:
        base = _WORKERS_DEFAULT.get(page_class, 1)

    return max(1, min(base, max_workers))


def enforce_memory_matrix(
    page_class: PageClass | str,
    max_workers: int = 2,
    *,
    table_backend: str = "paddle",
    vlm_backend: str = "none",
) -> int:
    """Validate the co-residency matrix and return the enforced worker count.

    This is the single entry point the orchestrator/runner should call.
    It logs the decision for observability and delegates to
    :func:`recommended_workers` for the actual count.
    """
    if isinstance(page_class, str):
        page_class = PageClass(page_class)

    workers = recommended_workers(
        page_class, max_workers, table_backend=table_backend
    )

    if table_backend == "mineru":
        resident = "MinerU subprocess"
    elif page_class == PageClass.TABLE_CANDIDATE:
        resident = "PyMuPDF + PP-StructureV3"
    elif page_class in (PageClass.CHART_CANDIDATE, PageClass.MIXED) and vlm_backend != "none":
        resident = "PyMuPDF + llama-server sidecar (VLM shared)"
    elif page_class in (PageClass.SCANNED, PageClass.MIXED):
        resident = "PyMuPDF + PP-OCRv6_small"
    else:
        resident = "PyMuPDF only"

    logger.debug(
        "memory_matrix: page_class=%s backend=%s resident='%s' workers=%d",
        page_class.value,
        table_backend,
        resident,
        workers,
    )
    return workers


def force_gc() -> None:
    gc.collect()

def release_page_resources(*objs) -> None:
    for obj in objs:
        if isinstance(obj, list):
            obj.clear()
        elif isinstance(obj, dict):
            obj.clear()
    objs = None
    force_gc()