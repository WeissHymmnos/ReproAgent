"""CLI entry point for finreportparser.

Commands:
  parse INPUT  — parse a single PDF to markdown + JSON
  batch DIR    — parse all PDFs in a directory (sequential, T28 will add multiprocessing)
  doctor       — check environment and dependencies
"""

import importlib
import importlib.util
import logging
import shutil
import sys
from pathlib import Path

import typer

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="finreportparser",
    help="Local Chinese financial report PDF parser",
    no_args_is_help=True,
)


@app.command()
def parse(
    input_pdf: str = typer.Argument(..., help="Path to the PDF file to parse."),
    mode: str = typer.Option(
        "balanced",
        "--mode",
        help="Quality mode: fast | balanced | max-quality",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Output directory (default: ./output or config out_dir).",
    ),
    sidecar: bool = typer.Option(
        False,
        "--sidecar/--no-sidecar",
        help="Write sidecar .md next to the PDF.",
    ),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Resume from cache if available.",
    ),
    workers: int | None = typer.Option(
        None,
        "--workers",
        help="Number of worker processes (default: config value).",
    ),
    table_backend: str | None = typer.Option(
        None,
        "--table-backend",
        help="Table extraction backend: paddle | mineru",
    ),
    vlm_backend: str | None = typer.Option(
        None,
        "--vlm-backend",
        help="VLM backend: none | paddle_vl | smolvlm | llamacpp_http",
    ),
    formula_backend: str | None = typer.Option(
        None,
        "--formula-backend",
        help="none|l1|pix2text|auto",
    ),
    image_max_edge: int | None = typer.Option(
        None,
        "--image-max-edge",
        help="Maximum edge length for rendered page images (512–768).",
    ),
) -> None:
    """Parse a single PDF file into markdown and JSON."""
    from finreportparser.config import load_config
    from finreportparser.extract.pdf_text import CorruptPdfError, EncryptedPdfError
    from finreportparser.pipeline.orchestrator import parse_pdf_to_files

    pdf_path = Path(input_pdf)
    if not pdf_path.is_file():
        typer.echo(f"Error: file not found: {pdf_path}", err=True)
        raise typer.Exit(code=1)

    overrides: dict = {"mode": mode}
    if out is not None:
        overrides["out_dir"] = out
    if sidecar:
        overrides["sidecar"] = True
    overrides["resume"] = resume
    if workers is not None:
        overrides["workers"] = workers
    if table_backend is not None:
        overrides["table_backend"] = table_backend
    if vlm_backend is not None:
        overrides["vlm_backend"] = vlm_backend
    if formula_backend is not None:
        overrides["formula_backend"] = formula_backend
    if image_max_edge is not None:
        overrides["image_max_edge"] = image_max_edge

    try:
        config = load_config(overrides=overrides)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    except Exception as e:
        typer.echo(f"Error: invalid configuration: {e}", err=True)
        raise typer.Exit(code=1) from None

    try:
        md_path, json_path = parse_pdf_to_files(
            pdf_path,
            config,
            out_dir=out,
            resume=resume,
        )
    except EncryptedPdfError as e:
        typer.echo(f"Error: encrypted PDF — {e}", err=True)
        raise typer.Exit(code=1) from None
    except CorruptPdfError as e:
        typer.echo(f"Error: corrupt or unreadable PDF — {e}", err=True)
        raise typer.Exit(code=1) from None
    except Exception as e:
        import traceback
        traceback.print_exc()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"markdown: {md_path}")
    typer.echo(f"json:     {json_path}")
    raise typer.Exit(code=0)


@app.command()
def batch(
    directory: str = typer.Argument(..., help="Directory containing PDF files."),
    mode: str = typer.Option("balanced", "--mode", help="Quality mode."),
    out: str | None = typer.Option(None, "--out", help="Output directory."),
    resume: bool = typer.Option(True, "--resume/--no-resume", help="Resume from cache."),
) -> None:
    """Parse all PDFs in a directory."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        typer.echo(f"Error: directory not found: {dir_path}", err=True)
        raise typer.Exit(code=1)

    from finreportparser.batch.runner import run_batch
    from finreportparser.config import load_config

    overrides: dict = {"mode": mode, "resume": resume}
    if out is not None:
        overrides["out_dir"] = out

    try:
        config = load_config(overrides=overrides)
    except Exception as e:
        typer.echo(f"Error: invalid configuration: {e}", err=True)
        raise typer.Exit(code=1) from None

    success, failed = run_batch(dir_path, config, out_dir=out, resume=resume)

    typer.echo(f"\nDone: {success} ok, {failed} failed")
    raise typer.Exit(code=0 if failed == 0 else 1)


@app.command()
def doctor() -> None:
    """Check environment, dependencies, and configuration."""
    issues = 0
    warnings = 0

    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    typer.echo(f"OK    python: {py_version}")

    if importlib.util.find_spec("fitz"):
        typer.echo("OK    pymupdf: available")
    else:
        typer.echo("FAIL  pymupdf: MISSING (required)")
        issues += 1

    if importlib.util.find_spec("paddleocr"):
        typer.echo("OK    paddleocr: available")
    else:
        typer.echo("WARN  paddleocr: not installed (OCR will be skipped)")
        warnings += 1

    if importlib.util.find_spec("paddle"):
        typer.echo("OK    paddlepaddle: available")
    else:
        typer.echo(
            "WARN  paddlepaddle: not installed "
            "(uv pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/)"
        )
        warnings += 1

    if importlib.util.find_spec("transformers"):
        typer.echo("OK    transformers: available")
    else:
        typer.echo("WARN  transformers: not installed (SmolVLM backend unavailable; uv sync --extra smolvlm)")
        warnings += 1

    llama_server = shutil.which("llama-server")
    if llama_server:
        typer.echo(f"OK    llama-server: {llama_server}")
    else:
        typer.echo("WARN  llama-server: not on PATH (llamacpp_http sidecar optional)")
        warnings += 1

    ram_gb: float | None = None
    try:
        import psutil
        mem = psutil.virtual_memory()
        ram_gb = mem.available / (1024 ** 3)
    except ImportError:
        try:
            meminfo_text = Path("/proc/meminfo").read_text()
            for line in meminfo_text.splitlines():
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    ram_gb = kb / (1024 ** 2)
                    break
        except (OSError, ValueError) as e:
            logger.debug("Could not read /proc/meminfo: %s", e)

    if ram_gb is not None:
        if ram_gb < 8.0:
            typer.echo(f"WARN  free RAM: {ram_gb:.1f} GB (< 8 GB recommended)")
            warnings += 1
        else:
            typer.echo(f"OK    free RAM: {ram_gb:.1f} GB")
    else:
        typer.echo("WARN  free RAM: unable to determine")
        warnings += 1

    try:
        from finreportparser.config import load_config
        config = load_config()
        model_dir = Path(config.model_dir)
        if model_dir.exists():
            typer.echo(f"OK    model_dir: {model_dir}")
        else:
            typer.echo(f"WARN  model_dir: {model_dir} (does not exist yet)")
            warnings += 1
    except Exception as e:
        typer.echo(f"WARN  model_dir: unable to check ({e})")
        warnings += 1

    if importlib.util.find_spec("openvino"):
        typer.echo("OK    openvino: available")
    else:
        typer.echo("INFO  openvino: not installed (optional, for accelerated inference)")

    if importlib.util.find_spec("onnxruntime"):
        typer.echo("OK    onnxruntime: available")
    else:
        typer.echo("INFO  onnxruntime: not installed (optional fallback)")

    try:
        config = load_config()
        if config.enable_hpi:
            typer.echo("INFO  HPI: enabled in config (will attempt to use OpenVINO/ONNX)")
        else:
            typer.echo("INFO  HPI: disabled in config")
    except Exception as e:
        logger.debug("Could not check HPI config: %s", e)

    if importlib.util.find_spec("pix2text"):
        typer.echo("OK    pix2text: available")
    else:
        typer.echo("WARN  pix2text: not installed (formula extraction will fallback to L1; uv sync --extra formula)")
        warnings += 1

    typer.echo("")
    if issues > 0:
        typer.echo(f"FAIL  {issues} issue(s), {warnings} warning(s)")
        raise typer.Exit(code=1)
    else:
        typer.echo(f"OK    0 issues, {warnings} warning(s)")
        raise typer.Exit(code=0)


def main() -> None:
    app()


if __name__ == "__main__":
    app()