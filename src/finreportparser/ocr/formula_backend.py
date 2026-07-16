from typing import Protocol

from finreportparser.types import FormulaMeta


class FormulaRecognizer(Protocol):
    def recognize(self, image_bytes: bytes) -> FormulaMeta | None: ...

class NullFormulaRecognizer:
    def recognize(self, image_bytes: bytes) -> FormulaMeta | None:
        return None

class Pix2TextRecognizer:
    def __init__(self):
        self._engine = None

    def _ensure_engine(self):
        if self._engine is not None:
            return
        try:
            from pix2text import Pix2Text
            self._engine = Pix2Text.from_config(device='cpu')
        except ImportError:
            self._engine = None

    def recognize(self, image_bytes: bytes) -> FormulaMeta | None:
        self._ensure_engine()
        if self._engine is None:
            return None

        try:
            import io

            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
            res = self._engine.recognize_formula(img)
            if res:
                return FormulaMeta(
                    latex=res,
                    source="pix2text",
                    confidence=1.0
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Pix2Text formula recognition failed: {e}")
        return None

def get_formula_backend(name: str) -> FormulaRecognizer:
    if name == "pix2text":
        return Pix2TextRecognizer()
    return NullFormulaRecognizer()
