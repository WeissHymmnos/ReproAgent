from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image


@dataclass
class OcrLine:
    text: str
    confidence: float
    bbox: list[list[float]] | None = None

class OcrEngine(Protocol):
    def predict(self, image: bytes | Path | Image.Image) -> list[OcrLine]:
        ...

    def unload(self) -> None:
        ...

class BaseTableExtractor(Protocol):
    estimated_ram_gb: float

    def extract_table(self, image: bytes | Path | Image.Image) -> str:
        ...

    def unload(self) -> None:
        ...
