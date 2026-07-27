from typing import Protocol

from finreportparser.types import ChartClassification, ChartMeta


class BaseVLMProvider(Protocol):
    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        ...

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        ...

    def unload(self) -> None:
        ...

    # Optional: real edge-VLM chart classification (classify-first pipeline)
    def classify_chart(self, image_bytes: bytes) -> ChartClassification | None:
        """Return visual classification; None if backend cannot classify."""
        ...
