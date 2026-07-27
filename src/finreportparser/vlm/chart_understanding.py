"""Classify-first chart understanding.

Order of operations (always):
  1. Classify chart type (edge VLM + OCR fusion when available)
  2. Describe with type-specific strategy
  3. Attach ChartClassification to ChartMeta
"""

from __future__ import annotations

import logging

from finreportparser.types import ChartClassification, ChartMeta, ChartType
from finreportparser.vlm.base import BaseVLMProvider
from finreportparser.vlm.chart_classify import CHART_TYPE_ZH

logger = logging.getLogger(__name__)


def understand_chart(image_bytes: bytes, provider: BaseVLMProvider | None) -> ChartMeta:
    """
    Understand a chart image using the provided VLM provider.

    Always classifies first when the provider supports it; description is
    type-conditioned.
    """
    if not provider:
        return ChartMeta(
            chart_type=ChartType.UNKNOWN.value,
            description="[Chart understanding skipped: No VLM provider]",
            title=None,
            data_points=None,
            classification=ChartClassification(
                chart_type=ChartType.UNKNOWN,
                confidence=0.0,
                source="fusion",
                rationale="no_provider",
            ),
        )

    try:
        # Prefer full describe_chart which implementations should run classify-first.
        meta = provider.describe_chart(image_bytes)
        if meta:
            # Ensure classification is populated
            if meta.classification is None and hasattr(provider, "classify_chart"):
                try:
                    meta.classification = provider.classify_chart(image_bytes)
                except Exception as e:
                    logger.debug("post-describe classify failed: %s", e)
            if meta.classification is not None and not meta.chart_type:
                meta.chart_type = meta.classification.chart_type.value
            return meta
    except Exception as e:
        logger.warning(f"VLM provider failed to describe chart: {e}")

    # Fallback: classify only
    cls = None
    if hasattr(provider, "classify_chart"):
        try:
            cls = provider.classify_chart(image_bytes)
        except Exception as e:
            logger.warning("classify_chart failed: %s", e)

    if cls is not None:
        zh = CHART_TYPE_ZH.get(cls.chart_type, cls.chart_type.value)
        return ChartMeta(
            chart_type=cls.chart_type.value,
            title=None,
            description=(
                f"【分类】{zh} conf={cls.confidence:.2f} source={cls.source}"
                f" — description unavailable"
            ),
            data_points=None,
            classification=cls,
        )

    return ChartMeta(
        chart_type=ChartType.UNKNOWN.value,
        description="[Chart understanding failed or returned no data]",
        title=None,
        data_points=None,
        classification=ChartClassification(
            chart_type=ChartType.UNKNOWN,
            confidence=0.0,
            source="fusion",
            rationale="failed",
        ),
    )
