"""Edge hybrid VLM: small vision model classify + Paddle OCR describe.

Designed for edge/CPU deployment:
  - Classifier: SmolVLM-256M-Instruct (or any client with classify_chart)
  - OCR/describe: PaddleOCR via PaddleVLProvider

Speed strategy:
  1. OCR prior first (cheap)
  2. Skip VLM when OCR confidence is high enough
  3. Reuse OCR lines for describe (no double OCR)
  4. Mermaid only for framework/flowchart, without re-classify
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

# Skip expensive edge VLM when OCR prior is already confident
_OCR_SKIP_VLM_THRESHOLD = 0.72


class EdgeHybridVLM:
    """Classify with edge VLM, describe with OCR, fuse both signals."""

    def __init__(
        self,
        *,
        classifier: Any | None = None,
        ocr_provider: Any | None = None,
        ocr_skip_vlm_threshold: float = _OCR_SKIP_VLM_THRESHOLD,
    ):
        self._classifier = classifier or SmolVlmProvider()
        self._ocr = ocr_provider or PaddleVLProvider()
        self._ocr_skip_vlm_threshold = ocr_skip_vlm_threshold
        # per-call cache to avoid double OCR within describe
        self._last_ocr_lines: list | None = None
        self._last_ocr_key: int | None = None

    def _ocr_lines(self, image_bytes: bytes) -> list:
        key = id(image_bytes) if not isinstance(image_bytes, (bytes, bytearray)) else hash(
            image_bytes[:64] + image_bytes[-64:] + len(image_bytes).to_bytes(4, "little")
        )
        if self._last_ocr_key == key and self._last_ocr_lines is not None:
            return self._last_ocr_lines
        lines: list = []
        try:
            if hasattr(self._ocr, "_run_ocr"):
                lines = self._ocr._run_ocr(image_bytes)  # noqa: SLF001
        except Exception as e:
            logger.warning("OCR failed: %s", e)
        self._last_ocr_key = key
        self._last_ocr_lines = lines
        return lines

    def classify_chart(self, image_bytes: bytes) -> ChartClassification:
        vlm_type: ChartType | None = None
        vlm_c: float | None = None
        ocr_type: ChartType | None = None
        ocr_c: float | None = None

        # --- OCR prior first (fast path) ---
        lines = self._ocr_lines(image_bytes)
        if lines:
            ocr_type, ocr_c, _ = ocr_prior_from_lines(lines)

        # --- Edge VLM only when OCR is weak/unknown ---
        need_vlm = (
            ocr_type is None
            or ocr_type == ChartType.UNKNOWN
            or (ocr_c or 0.0) < self._ocr_skip_vlm_threshold
        )
        if need_vlm:
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
        else:
            logger.debug(
                "Skip VLM classify (OCR %s conf=%.2f)",
                ocr_type,
                ocr_c or 0.0,
            )

        return fuse_classification(
            vlm_type=vlm_type,
            vlm_confidence=vlm_c,
            ocr_type=ocr_type,
            ocr_confidence=ocr_c,
        )

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        # 1) Classify first (OCR-first, maybe skip VLM)
        classification = self.classify_chart(image_bytes)
        chart_type = classification.chart_type

        # 2) OCR structured description — reuse lines when possible
        meta: ChartMeta | None = None
        try:
            if hasattr(self._ocr, "describe_chart_as"):
                # Prefer path that uses precomputed lines if we add it; else normal
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

        meta.chart_type = chart_type.value
        meta.classification = classification

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

    def diagram_to_mermaid_candidates(
        self, image_bytes: bytes, chart_type: str | ChartType | None = None
    ) -> list[str]:
        """Generate mermaid only for structure diagrams. Pass chart_type to skip re-classify."""
        if chart_type is not None:
            ctype = (
                chart_type
                if isinstance(chart_type, ChartType)
                else ChartType(str(chart_type))
            )
        else:
            ctype = self.classify_chart(image_bytes).chart_type

        if ctype not in (ChartType.FRAMEWORK, ChartType.FLOWCHART):
            return []
        if hasattr(self._ocr, "diagram_to_mermaid_candidates"):
            codes = self._ocr.diagram_to_mermaid_candidates(image_bytes) or []
            if codes:
                return codes
        return []

    def unload(self) -> None:
        self._last_ocr_lines = None
        self._last_ocr_key = None
        for eng in (self._classifier, self._ocr):
            if eng is not None and hasattr(eng, "unload"):
                try:
                    eng.unload()
                except Exception:
                    pass
