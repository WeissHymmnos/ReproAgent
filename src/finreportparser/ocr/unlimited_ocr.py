import io
from pathlib import Path

from PIL import Image

from finreportparser.models.unlimited_ocr_core import global_unlimited_ocr_manager
from finreportparser.ocr.base import BaseTableExtractor, OcrEngine, OcrLine


class UnlimitedOcrTableExtractor(BaseTableExtractor):
    estimated_ram_gb: float = 6.0

    def extract_table(self, image: bytes | Path | Image.Image) -> str:
        if isinstance(image, Path):
            image = image.read_bytes()
        elif isinstance(image, Image.Image):
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG")
            image = buf.getvalue()
        elif not isinstance(image, bytes):
            raise ValueError("Unsupported image type")
            
        markdown = global_unlimited_ocr_manager.predict(image, task="table")
        return markdown

    def unload(self) -> None:
        global_unlimited_ocr_manager.unload()

class UnlimitedOcrEngine(OcrEngine):
    def predict(self, image: bytes | Path | Image.Image) -> list[OcrLine]:
        if isinstance(image, Path):
            image = image.read_bytes()
        elif isinstance(image, Image.Image):
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG")
            image = buf.getvalue()
            
        # Unlimited-OCR natively gives markdown. To adapt to OcrEngine which expects lines with bboxes,
        # we can just return one big OcrLine block or attempt to parse it.
        # Since we use it as a full-page Markdown parser, this method might just wrap the whole markdown text.
        markdown = global_unlimited_ocr_manager.predict(image, task="markdown")
        
        # Bbox information is generally not provided out of the box in the same format.
        # We will return the whole parsed page as a single block for compatibility, 
        # but optimally the pipeline should use the full page markdown directly.
        return [OcrLine(text=markdown, confidence=1.0, bbox=None)]

    def unload(self) -> None:
        global_unlimited_ocr_manager.unload()
