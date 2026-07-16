"""PDF 布局提取 → Markdown。"""

from __future__ import annotations

from typing import Literal

from reproagent.models.report import ResearchReport


class LayoutExtractor:
    """Marker / LlamaParse / MinerU 后端，提取高保真 Markdown。

    重依赖请 lazy import，避免未装 optional extras 时 import 失败。
    """

    def __init__(
        self,
        backend: Literal["finpdfpro", "marker", "llamaparse", "mineru"] = "finpdfpro",
    ) -> None:
        self.backend = backend

    def extract(self, report: ResearchReport) -> str:
        """返回完整 Markdown 文本。"""
        raise NotImplementedError(f"LayoutExtractor.extract(backend={self.backend})")
