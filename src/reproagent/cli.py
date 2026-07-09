"""Typer CLI：ingest / reproduce / library / review / tui。"""

from __future__ import annotations

from pathlib import Path

import typer

from reproagent import __version__

app = typer.Typer(
    name="reproagent",
    help="研报因子复现系统",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"reproagent {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="显示版本号",
    ),
) -> None:
    """ReproAgent CLI。"""


@app.command()
def ingest(pdf_path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """摄入一篇研报。"""
    # TODO: upload_pdf → validate_pdf → 持久化
    typer.echo(f"[stub] ingest {pdf_path}")
    raise typer.Exit(code=1)


@app.command()
def reproduce(pdf_path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """端到端：摄入 → 解析 → 复现 → 偏差 → 入库。"""
    # TODO: pipeline.reproduce_report(pdf_path, get_settings())
    typer.echo(f"[stub] reproduce {pdf_path}")
    raise typer.Exit(code=1)


@app.command()
def library(
    style: str | None = typer.Option(None, "--style", "-s", help="按风格过滤"),
) -> None:
    """浏览因子库。"""
    # TODO: FactorLibraryManager.list(LibraryFilter(style=style))
    typer.echo(f"[stub] library style={style!r}")
    raise typer.Exit(code=1)


@app.command()
def review() -> None:
    """处理人工复核队列。"""
    # TODO: dequeue_manual_review / confirm_manual_review
    typer.echo("[stub] review")
    raise typer.Exit(code=1)


@app.command()
def tui() -> None:
    """启动 TUI。"""
    from reproagent.tui.app import ReproAgentApp

    ReproAgentApp().run()
