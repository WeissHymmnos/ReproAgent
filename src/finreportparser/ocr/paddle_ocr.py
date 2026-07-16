import gc
from pathlib import Path

import numpy as np
from PIL import Image

from finreportparser.ocr.base import OcrEngine, OcrLine


class PaddleOcrEngine(OcrEngine):
    def __init__(self, lang: str = "ch", cpu_threads: int = 4, enable_hpi: bool = False):
        self.lang = lang
        self.cpu_threads = cpu_threads
        self.enable_hpi = enable_hpi
        self._engine = None
        self._ensure_engine()

    def _ensure_engine(self):
        if self._engine is not None:
            return

        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise ImportError(
                "PaddleOCR is not installed. Please install it using:\n"
                "uv pip install paddlepaddle==3.2.0 paddleocr\n"
                "Note: Use CPU version for ThinkPad compatibility."
            ) from e

        kwargs = {
            "use_angle_cls": True,
            "lang": self.lang,
            "use_gpu": False,
            "cpu_threads": self.cpu_threads,
            "show_log": False,
        }

        if self.enable_hpi:
            kwargs["enable_hpi"] = True

        try:
            self._engine = PaddleOCR(**kwargs)
        except TypeError:
            if "enable_hpi" in kwargs:
                kwargs.pop("enable_hpi")
                self._engine = PaddleOCR(**kwargs)
            else:
                raise

    def predict(self, image: bytes | Path | Image.Image) -> list[OcrLine]:
        self._ensure_engine()

        img_input = image
        if isinstance(image, Path):
            img_input = str(image)
        elif isinstance(image, Image.Image):
            img_input = np.array(image.convert('RGB'))
        elif isinstance(image, bytes):
            import io
            img = Image.open(io.BytesIO(image)).convert('RGB')
            img_input = np.array(img)

        result = self._engine.ocr(img_input, cls=True)

        lines = []
        if not result or not result[0]:
            return lines

        for line in result[0]:
            bbox, (text, confidence) = line
            lines.append(OcrLine(
                text=text,
                confidence=float(confidence),
                bbox=bbox
            ))

        return lines

    def unload(self) -> None:
        self._engine = None
        gc.collect()
