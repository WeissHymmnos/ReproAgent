"""Edge hybrid VLM: small vision model classify + Paddle OCR describe.

Designed for edge/CPU deployment:
  - Classifier: SmolVLM-256M-Instruct (or any client with classify_chart)
  - OCR/describe: PaddleOCR via PaddleVLProvider

Pipeline:
  classify(VLM) + classify(OCR) → fuse → type-specific description
"""

from __future__ import annotations

import logging
from typing import Any

from finreportparser.types import ChartClassification, ChartMeta, ChartType
from finreportparser.vlm.chart_classify import (
    CHART_TYPE_ZH,
    fuse_classification,
    ocr_prior_from_lines,
)
from finreportparser.vlm.paddle_vl import PaddleVLProvider
from finreportparser.vlm.smolvlm import SmolVlmProvider

logger = logging.getLogger(__name__)


class EdgeHybridVLM:
    """Classify with edge VLM, describe with OCR, fuse both signals."""

    def __init__(
        self,
        *,
        classifier: Any | None = None,
        ocr_provider: Any | None = None,
    ):
        self._classifier = classifier or SmolVlmProvider()
        self._ocr = ocr_provider or PaddleVLProvider()

    def classify_chart(self, image_bytes: bytes) -> ChartClassification:
        vlm_type: ChartType | None = None
        vlm_c: float | None = None
        ocr_type: ChartType | None = None
        ocr_c: float | None = None

        # --- Edge VLM visual classification ---
        try:
            if hasattr(self._classifier, "classify_chart"):
                vlm_cls = self._classifier.classify_chart(image_bytes)
                if vlm_cls is not None:
                    vlm_type = (
                        vlm_cls.chart_type
                        if isinstance(vlm_cls.chart_type, ChartType)
                        else ChartType(str(vlm_cls.chart_type))
                    )
                    vlm_c = float(vlm_cls.confidence or 0.0)
        except Exception as e:
            logger.warning("Edge VLM classify failed: %s", e)

        # --- OCR prior ---
        try:
            lines = []
            if hasattr(self._ocr, "_run_ocr"):
                lines = self._ocr._run_ocr(image_bytes)  # noqa: SLF001 — shared OCR path
            if lines:
                ocr_type, ocr_c, _ = ocr_prior_from_lines(lines)
        except Exception as e:
            logger.warning("OCR classify prior failed: %s", e)

        return fuse_classification(
            vlm_type=vlm_type,
            vlm_confidence=vlm_c,
            ocr_type=ocr_type,
            ocr_confidence=ocr_c,
        )

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        # 1) Classify first
        classification = self.classify_chart(image_bytes)
        chart_type = classification.chart_type

        # 2) OCR structured description, guided by classification
        meta: ChartMeta | None = None
        try:
            if hasattr(self._ocr, "describe_chart_as"):
                meta = self._ocr.describe_chart_as(image_bytes, chart_type)
            else:
                meta = self._ocr.describe_chart(image_bytes)
        except Exception as e:
            logger.warning("OCR describe failed: %s", e)
            meta = None

        if meta is None:
            zh = CHART_TYPE_ZH.get(chart_type, "图表")
            meta = ChartMeta(
                chart_type=chart_type.value,
                title="Chart",
                description=f"[{zh}] 分类完成，但描述失败",
                data_points=[],
            )

        # Force fused type onto meta
        meta.chart_type = chart_type.value
        meta.classification = classification

        # Prefix description with classification banner for markdown clarity
        zh = CHART_TYPE_ZH.get(chart_type, chart_type.value)
        banner = (
            f"【分类】{zh}（{chart_type.value}）"
            f" conf={classification.confidence:.2f}"
            f" source={classification.source}"
        )
        if classification.rationale:
            banner += f" ({classification.rationale})"
        if classification.vlm_type or classification.ocr_type:
            banner += (
                f" | VLM={classification.vlm_type}:{classification.vlm_confidence}"
                f" OCR={classification.ocr_type}:{classification.ocr_confidence}"
            )
        desc = meta.description or ""
        if not desc.startswith("【分类】"):
            meta.description = f"{banner}\n{desc}"
        return meta

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        cls = self.classify_chart(image_bytes)
        if cls.chart_type not in (ChartType.FRAMEWORK, ChartType.FLOWCHART):
            return []
        # Prefer OCR-layout mermaid when available
        if hasattr(self._ocr, "diagram_to_mermaid_candidates"):
            codes = self._ocr.diagram_to_mermaid_candidates(image_bytes) or []
            if codes:
                return codes
        if hasattr(self._classifier, "diagram_to_mermaid_candidates"):
            return self._classifier.diagram_to_mermaid_candidates(image_bytes) or []
        return []

    def unload(self) -> None:
        for eng in (self._classifier, self._ocr):
            if eng is not None and hasattr(eng, "unload"):
                try:
                    eng.unload()
                except Exception:
                    pass
