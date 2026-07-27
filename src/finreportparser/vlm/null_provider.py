from finreportparser.types import ChartClassification, ChartMeta, ChartType


class NullVLM:
    def classify_chart(self, image_bytes: bytes) -> ChartClassification | None:
        return ChartClassification(
            chart_type=ChartType.UNKNOWN,
            confidence=0.0,
            source="fusion",
            rationale="vlm_disabled",
        )

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        return ChartMeta(
            chart_type=ChartType.UNKNOWN.value,
            title="Unknown Chart",
            description="VLM is disabled. Chart description not available.",
            data_points=[],
            classification=self.classify_chart(image_bytes),
        )

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        return []

    def unload(self) -> None:
        pass
