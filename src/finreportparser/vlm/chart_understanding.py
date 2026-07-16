import logging

from finreportparser.types import ChartMeta
from finreportparser.vlm.base import BaseVLMProvider

logger = logging.getLogger(__name__)

def understand_chart(image_bytes: bytes, provider: BaseVLMProvider | None) -> ChartMeta:
    """
    Understand a chart image using the provided VLM provider.
    Returns a default/empty ChartMeta if the provider is unavailable or fails.
    """
    if not provider:
        return ChartMeta(
            chart_type="unknown",
            description="[Chart understanding skipped: No VLM provider]",
            title=None,
            data_points=None
        )

    try:
        meta = provider.describe_chart(image_bytes)
        if meta:
            return meta
    except Exception as e:
        logger.warning(f"VLM provider failed to describe chart: {e}")

    return ChartMeta(
        chart_type="unknown",
        description="[Chart understanding failed or returned no data]",
        title=None,
        data_points=None
    )
