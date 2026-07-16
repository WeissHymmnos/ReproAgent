from typing import Protocol

from finreportparser.types import ChartMeta


class BaseVLMProvider(Protocol):
    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        ...

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        ...

    def unload(self) -> None:
        ...
