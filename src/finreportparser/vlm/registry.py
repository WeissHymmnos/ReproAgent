from finreportparser.vlm.base import BaseVLMProvider
from finreportparser.vlm.null_provider import NullVLM


def get_vlm(backend: str) -> BaseVLMProvider:
    if backend == "none":
        return NullVLM()
    elif backend == "paddle_vl":
        from finreportparser.vlm.paddle_vl import PaddleVLProvider
        return PaddleVLProvider()
    elif backend == "llamacpp_http":
        from finreportparser.vlm.llamacpp_http import LlamaCppHttpProvider
        return LlamaCppHttpProvider()
    elif backend == "smolvlm":
        from finreportparser.vlm.smolvlm import SmolVlmProvider
        return SmolVlmProvider()
    elif backend == "unlimited-ocr":
        from finreportparser.vlm.unlimited_ocr import UnlimitedOcrProvider
        return UnlimitedOcrProvider()
    else:
        return NullVLM()
