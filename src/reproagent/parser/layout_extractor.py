"""PDF 布局提取 → Markdown。"""

from __future__ import annotations

from typing import Literal

from reproagent.exceptions import ConfigurationError, ParseError
from reproagent.models.report import ResearchReport
from reproagent.settings import Settings, get_settings


class LayoutExtractor:
    """Marker / LlamaParse / MinerU 后端，提取高保真 Markdown。

    重依赖请 lazy import，避免未装 optional extras 时 import 失败。
    """

    def __init__(
        self,
        backend: Literal["finpdfpro", "marker", "llamaparse", "mineru"] = "finpdfpro",
        settings: Settings | None = None,
    ) -> None:
        self.backend = backend
        self.settings = settings or get_settings()

    def extract(self, report: ResearchReport) -> str:
        """返回完整 Markdown 文本。"""
        if self.backend != "finpdfpro":
            raise ConfigurationError(f"Only finpdfpro backend is supported, got {self.backend}")

        try:
            from finreportparser.extract.pdf_text import CorruptPdfError
            from finreportparser.pipeline.orchestrator import load_config, parse_pdf
        except ImportError as e:
            raise ConfigurationError(f"finreportparser is not installed: {e}")

        try:
            from finreportparser.output.markdown import render_markdown
        except ImportError:
            render_markdown = None

        try:
            config = load_config(overrides={
                "mode": self.settings.finpdfpro_mode,
                "vlm_backend": self.settings.finpdfpro_vlm_backend,
            })
            
            doc = parse_pdf(report.file_path, config=config)
            
            if render_markdown:
                return render_markdown(doc)
            else:
                md_parts = []
                for page in doc.pages:
                    for block in page.blocks:
                        md_parts.append(block.text)
                return "\n\n".join(md_parts)
                
        except CorruptPdfError as e:
            raise ParseError(f"Failed to parse PDF: {e}")
