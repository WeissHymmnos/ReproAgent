"""PDF 布局提取 → Markdown（优先 finpdfpro 0.5+ 源树）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from reproagent.exceptions import ConfigurationError, ParseError
from reproagent.models.report import ResearchReport
from reproagent.settings import Settings, get_settings


def prefer_latest_finpdfpro() -> Path | None:
    """Put ``finpdfpro/src`` first so we do not import the 0.2.0 vendor copy."""
    seen: set[Path] = set()
    starts = [Path(__file__).resolve(), Path.cwd().resolve()]
    try:
        starts.append(Path.cwd().parent.resolve())
    except OSError:
        pass
    for start in starts:
        for parent in (start, *start.parents):
            cand = parent / "finpdfpro" / "src"
            marker = cand / "finreportparser" / "pipeline" / "orchestrator.py"
            if not marker.is_file():
                continue
            try:
                resolved = cand.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            path = str(resolved)
            if path in sys.path:
                sys.path.remove(path)
            sys.path.insert(0, path)
            return resolved
    return None


def _parser_identity() -> dict[str, str]:
    prefer_latest_finpdfpro()
    import finreportparser

    return {
        "module": str(getattr(finreportparser, "__file__", "")),
        "version": str(getattr(finreportparser, "__version__", "")),
    }


class LayoutExtractor:
    """finpdfpro 0.5+ orchestrator + profile + formula L1 → Markdown."""

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

        src = prefer_latest_finpdfpro()

        try:
            import finreportparser
            from finreportparser.config import load_config
            from finreportparser.extract.pdf_text import CorruptPdfError, EncryptedPdfError
            from finreportparser.output.markdown import render_markdown
            from finreportparser.pipeline.orchestrator import parse_pdf
        except ImportError as e:
            raise ConfigurationError(f"finreportparser is not importable: {e}") from e

        version = str(getattr(finreportparser, "__version__", "0"))
        module_file = Path(str(getattr(finreportparser, "__file__", "")))
        in_tree = src is not None or "finpdfpro" in str(module_file)
        if version.startswith("0.2"):
            raise ConfigurationError(
                f"expected finpdfpro>=0.5.0, got {version} from {module_file}"
            )
        if not in_tree and not version.startswith("0.5"):
            raise ConfigurationError(
                f"expected finpdfpro>=0.5.0, got {version} from {module_file}"
            )

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
            return render_markdown(
                doc,
                strip_headers_footers=bool(getattr(config, "strip_headers_footers", True)),
                append_text_layer=bool(getattr(config, "append_text_layer", False)),
            )
        except EncryptedPdfError as e:
            raise ParseError(f"Failed to parse encrypted PDF: {e}") from e
        except CorruptPdfError as e:
            raise ParseError(f"Failed to parse PDF: {e}") from e
