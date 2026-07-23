import logging

from finreportparser.models.unlimited_ocr_core import global_unlimited_ocr_manager
from finreportparser.types import ChartMeta
from finreportparser.vlm.base import BaseVLMProvider

logger = logging.getLogger(__name__)

class UnlimitedOcrProvider(BaseVLMProvider):
    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        try:
            description = global_unlimited_ocr_manager.predict(image_bytes, task="chart")
            
            chart_type = "unknown"
            desc_lower = description.lower()
            if "bar" in desc_lower:
                chart_type = "bar"
            elif "line" in desc_lower:
                chart_type = "line"
            elif "pie" in desc_lower:
                chart_type = "pie"

            return ChartMeta(
                chart_type=chart_type,
                title="Unlimited-OCR Chart",
                description=description.strip(),
                data_points=[]
            )
        except Exception as e:
            logger.error(f"Error describing chart with Unlimited-OCR: {e}")
            return ChartMeta(
                chart_type="unknown",
                title="Error",
                description=f"Failed to describe chart: {e}",
                data_points=[]
            )

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        try:
            description = global_unlimited_ocr_manager.predict(image_bytes, task="mermaid")
            
            if "```mermaid" in description:
                parts = description.split("```mermaid")
                if len(parts) > 1:
                    code = parts[1].split("```")[0].strip()
                    return [code]
            elif "```" in description:
                parts = description.split("```")
                if len(parts) > 1:
                    code = parts[1].strip()
                    if code.startswith("graph") or code.startswith("flowchart") or code.startswith("pie"):
                        return [code]

            return [description.strip()]
        except Exception as e:
            logger.error(f"Error converting diagram to mermaid with Unlimited-OCR: {e}")
            return []

    def unload(self) -> None:
        global_unlimited_ocr_manager.unload()
