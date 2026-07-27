import gc
import io
from pathlib import Path

import numpy as np
from PIL import Image

from finreportparser.ocr.base import OcrEngine, OcrLine


def _to_quad(box) -> list:
    """Normalize a bbox to a 4-point quad [[x,y], ...]."""
    arr = np.asarray(box)
    if arr.ndim == 2 and arr.shape[0] >= 4 and arr.shape[1] >= 2:
        return [[float(p[0]), float(p[1])] for p in arr[:4]]
    if arr.ndim == 1 and arr.shape[0] >= 4:
        x0, y0, x1, y1 = map(float, arr[:4])
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]


def _parse_ocr_result(result) -> list[OcrLine]:
    """Parse both PaddleOCR 2.x and 3.x result layouts into OcrLine list."""
    lines: list[OcrLine] = []
    if not result:
        return lines

    # PaddleOCR 3.x: list[dict|OCRResult] with rec_texts / rec_scores / dt_polys
    first = result[0] if isinstance(result, list) else result
    if isinstance(first, dict) or hasattr(first, "get"):
        page = first
        texts = page.get("rec_texts") if hasattr(page, "get") else None
        if texts is not None:
            scores = page.get("rec_scores") or [1.0] * len(texts)
            polys = page.get("rec_polys") or page.get("dt_polys") or []
            for i, text in enumerate(texts):
                if not text or not str(text).strip():
                    continue
                conf = float(scores[i]) if i < len(scores) else 1.0
                poly = polys[i] if i < len(polys) else None
                lines.append(
                    OcrLine(
                        text=str(text).strip(),
                        confidence=conf,
                        bbox=_to_quad(poly) if poly is not None else _to_quad([0, 0, 0, 0]),
                    )
                )
            return lines

    # PaddleOCR 2.x: [[[bbox, (text, conf)], ...]]
    page_lines = result[0] if isinstance(result, list) else result
    if not page_lines:
        return lines
    for line in page_lines:
        try:
            bbox, (text, confidence) = line
            if text and str(text).strip():
                lines.append(
                    OcrLine(
                        text=str(text).strip(),
                        confidence=float(confidence),
                        bbox=_to_quad(bbox),
                    )
                )
        except (TypeError, ValueError, IndexError):
            continue
    return lines


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

        # PaddleOCR 3.x uses different kwargs than 2.x — try modern first, then legacy.
        attempts = [
            {
                "lang": self.lang,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": True,
            },
            {"lang": self.lang},
            {
                "use_angle_cls": True,
                "lang": self.lang,
                "use_gpu": False,
                "cpu_threads": self.cpu_threads,
                "show_log": False,
            },
            {
                "use_angle_cls": True,
                "lang": self.lang,
            },
            {},
        ]
        if self.enable_hpi:
            attempts = [{**a, "enable_hpi": True} for a in attempts] + attempts

        last_err: Exception | None = None
        for kwargs in attempts:
            try:
                self._engine = PaddleOCR(**kwargs)
                return
            except (TypeError, ValueError) as e:
                last_err = e
                continue
        raise RuntimeError(f"Failed to initialize PaddleOCR: {last_err}")

    def predict(self, image: bytes | Path | Image.Image) -> list[OcrLine]:
        self._ensure_engine()

        img_input = image
        if isinstance(image, Path):
            img_input = str(image)
        elif isinstance(image, Image.Image):
            img_input = np.array(image.convert("RGB"))
        elif isinstance(image, bytes):
            img = Image.open(io.BytesIO(image)).convert("RGB")
            img_input = np.array(img)

        # Prefer predict() (3.x); fall back to ocr() (2.x / deprecated 3.x).
        result = None
        if hasattr(self._engine, "predict"):
            try:
                result = self._engine.predict(img_input)
            except Exception:
                result = None
        if result is None:
            try:
                result = self._engine.ocr(img_input, cls=True)
            except TypeError:
                result = self._engine.ocr(img_input)

        return _parse_ocr_result(result)

    def unload(self) -> None:
        self._engine = None
        gc.collect()
