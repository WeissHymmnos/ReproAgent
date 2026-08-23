"""PDF 布局提取 → Markdown。"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any, Literal

from reproagent.exceptions import ConfigurationError, ParseError
from reproagent.models.report import ResearchReport
from reproagent.settings import Settings, get_settings


def prefer_latest_finpdfpro() -> Path | None:
    """Prefer a sibling ``Documents/finpdfpro/src`` tree when it exists."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "finpdfpro" / "src"
        if (cand / "finreportparser" / "pipeline" / "orchestrator.py").is_file():
            path = str(cand)
            if path in sys.path:
                sys.path.remove(path)
            sys.path.insert(0, path)
            return cand
    return None


def load_finreportparser() -> Any:
    """Import finreportparser without evicting an already-loaded copy.

    Prefer a sibling 0.5+ tree on first import. If the in-repo 0.2.0 vendor
    is already in ``sys.modules`` (tests, other tools), keep it — it can parse.
    """
    if "finreportparser" not in sys.modules:
        prefer_latest_finpdfpro()
    import finreportparser

    return finreportparser


def _parser_identity() -> dict[str, str]:
    mod = load_finreportparser()
    return {
        "module": str(getattr(mod, "__file__", "")),
        "version": str(getattr(mod, "__version__", "")),
    }


def _render_document(doc: Any, config: Any, render_markdown: Any) -> str:
    if render_markdown is None:
        parts: list[str] = []
        for page in getattr(doc, "pages", []) or []:
            for block in getattr(page, "blocks", []) or []:
                text = getattr(block, "text", None)
                if text:
                    parts.append(str(text))
        return "\n\n".join(parts)
    kwargs: dict[str, Any] = {}
    try:
        sig = inspect.signature(render_markdown)
        if "strip_headers_footers" in sig.parameters:
            kwargs["strip_headers_footers"] = bool(
                getattr(config, "strip_headers_footers", True)
            )
        if "append_text_layer" in sig.parameters:
            kwargs["append_text_layer"] = bool(
                getattr(config, "append_text_layer", False)
            )
    except (TypeError, ValueError):
        kwargs = {}
    return render_markdown(doc, **kwargs)


class LayoutExtractor:
    """finreportparser orchestrator → Markdown (sibling 0.5+ or vendored)."""

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
            raise ConfigurationError(
                f"Only finpdfpro backend is supported, got {self.backend}"
            )

        load_finreportparser()
        try:
            from finreportparser.config import load_config
            from finreportparser.extract.pdf_text import CorruptPdfError
            from finreportparser.pipeline.orchestrator import parse_pdf
        except ImportError as e:
            raise ConfigurationError(f"finreportparser is not importable: {e}") from e

        encrypted_cls: type[BaseException] | None = None
        try:
            from finreportparser.extract.pdf_text import EncryptedPdfError as _Enc

            encrypted_cls = _Enc
        except ImportError:
            encrypted_cls = None

        try:
            from finreportparser.output.markdown import render_markdown
        except ImportError:
            render_markdown = None

        overrides: dict = {
            "profile": getattr(self.settings, "finpdfpro_profile", None) or "balanced",
            "vlm_backend": self.settings.finpdfpro_vlm_backend,
            "formula_backend": getattr(self.settings, "finpdfpro_formula_backend", None)
            or "l1",
            "resume": True,
            "cache_dir": str(self.settings.cache_dir / "finpdfpro"),
            "out_dir": str(self.settings.cache_dir / "finpdfpro_out"),
            "strip_headers_footers": True,
            "reading_order": "columns",
            "parse_method": "auto",
        }
        mode = getattr(self.settings, "finpdfpro_mode", None)
        if mode:
            overrides["mode"] = mode
        if overrides["vlm_backend"] and overrides["vlm_backend"] != "none":
            overrides["allow_vlm"] = True

        try:
            config = load_config(overrides=overrides)
            doc = parse_pdf(report.file_path, config=config)
            return _render_document(doc, config, render_markdown)
        except CorruptPdfError as e:
            raise ParseError(f"Failed to parse PDF: {e}") from e
        except Exception as e:
            if encrypted_cls is not None and isinstance(e, encrypted_cls):
                raise ParseError(f"Failed to parse encrypted PDF: {e}") from e
            raise
