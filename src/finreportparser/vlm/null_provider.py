
from finreportparser.types import ChartMeta
from finreportparser.vlm.base import BaseVLMProvider


class NullVLM(BaseVLMProvider):
    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        return ChartMeta(
            chart_type="unknown",
            title="Unknown Chart",
            description="VLM is disabled. Chart description not available.",
            data_points=[]
        )

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        return []

    def unload(self) -> None:
        pass
