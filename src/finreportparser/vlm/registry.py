from finreportparser.vlm.base import BaseVLMProvider
from finreportparser.vlm.null_provider import NullVLM


def get_vlm(backend: str) -> BaseVLMProvider:
    """Resolve VLM backend by name.

    Recommended for accuracy on edge hardware:
      edge — SmolVLM-256M classify + PaddleOCR describe/fusion
    """
    if backend == "none":
        return NullVLM()
    if backend == "paddle_vl":
        from finreportparser.vlm.paddle_vl import PaddleVLProvider

        return PaddleVLProvider()
    if backend == "llamacpp_http":
        from finreportparser.vlm.llamacpp_http import LlamaCppHttpProvider

        return LlamaCppHttpProvider()
    if backend == "smolvlm":
        from finreportparser.vlm.smolvlm import SmolVlmProvider

        return SmolVlmProvider()
    if backend in ("edge", "hybrid", "edge_hybrid"):
        from finreportparser.vlm.edge_hybrid import EdgeHybridVLM

        return EdgeHybridVLM()
    if backend == "unlimited-ocr":
        from finreportparser.vlm.unlimited_ocr import UnlimitedOcrProvider

        return UnlimitedOcrProvider()
    return NullVLM()
