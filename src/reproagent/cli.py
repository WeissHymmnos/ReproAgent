"""Typer CLI：ingest / reproduce / library / review / tui。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from reproagent import __version__
from reproagent.settings import get_settings

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


def _build_repository() -> Any:
    """构造一个默认 Repository（初始化 DB）。"""
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.repository import Repository

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine(settings.db_path)
    init_db(engine)
    return Repository(engine)


def _build_library_manager() -> Any:
    """构造 FactorLibraryManager。"""
    from reproagent.library.manager import FactorLibraryManager
    from reproagent.persistence.paths import AppPaths

    settings = get_settings()
    repo = _build_repository()
    paths = AppPaths.from_settings(settings)
    paths.ensure_layout()
    return FactorLibraryManager(repository=repo, paths=paths)


@app.command()
def ingest(pdf_path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """摄入一篇研报：upload → validate → 持久化。"""
    from reproagent.ingestion.uploader import upload_pdf
    from reproagent.ingestion.validator import validate_pdf

    report = upload_pdf(pdf_path)
    report = validate_pdf(report)

    if report.validation_status == "invalid":
        typer.echo(
            f"ingest failed: validation_status=invalid errors={report.validation_errors}",
            err=True,
        )
        try:
            repo = _build_repository()
            repo.save_report(report)
            from reproagent.ingestion.review_queue import enqueue_manual_review

            enqueue_manual_review(report, "validation_failed", repo=repo)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"warn: could not enqueue review: {exc}", err=True)
        raise typer.Exit(code=1)

    repo = _build_repository()
    repo.save_report(report)

    typer.echo(
        "ingest ok: "
        f"id={report.id} hash={report.file_hash[:12]}… "
        f"status={report.validation_status} pages={report.page_count}"
    )


@app.command()
def reproduce(pdf_path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """端到端：摄入 → 解析 → 复现 → 偏差 → 入库。"""
    try:
        from reproagent.pipeline import reproduce_report
    except ImportError as exc:
        typer.echo(f"reproduce unavailable: pipeline import failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    settings = get_settings()
    if settings.is_prod and not settings.mock_llm_allowed:
        key = settings.llm_api_key.get_secret_value().strip()
        if not key:
            typer.echo(
                "reproduce failed: APP_ENV=prod requires LLM_API_KEY "
                "(or set ALLOW_MOCK_LLM=true for offline).",
                err=True,
            )
            raise typer.Exit(code=1)

    try:
        result = reproduce_report(Path(pdf_path), settings)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"reproduce failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("reproduce ok")
    if result is not None:
        try:
            typer.echo(json.dumps(result, default=str, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            typer.echo(str(result))


@app.command()
def library(
    style: str | None = typer.Option(None, "--style", "-s", help="按风格过滤"),
    html: bool = typer.Option(False, "--html", help="生成 HTML 仪表盘到 wiki_dir"),
) -> None:
    """浏览因子库。"""
    from reproagent.models.library import LibraryFilter

    manager = _build_library_manager()
    filter_ = LibraryFilter(style=style) if style else None
    entries = manager.list(filter_)

    if not entries:
        typer.echo("library: empty (0 factors)")
        if html:
            typer.echo("--html requested but library empty; skipping dashboard")
        return

    typer.echo(f"library: {len(entries)} factor(s)")
    typer.echo(f"{'id':<34} {'name':<24} {'style':<12} {'status':<10} {'version':<10}")
    typer.echo("-" * 96)
    for entry in entries:
        typer.echo(
            f"{entry.id:<34} {entry.factor.name:<24} {entry.factor.style:<12} "
            f"{entry.status:<10} {entry.version:<10}"
        )

    if html:
        from reproagent.library.dashboard import generate_html_dashboard

        settings = get_settings()
        out = settings.wiki_dir / "dashboard.html"
        factors_payload = [
            {
                "name": entry.factor.name,
                "ic_series": [],
                "excess_cum": [],
                "stats": {},
            }
            for entry in entries
        ]
        generate_html_dashboard(factors_payload, out)
        typer.echo(f"html dashboard -> {out}")


@app.command()
def review(
    list_queue: bool = typer.Option(False, "--list", "-l", help="仅列出待审项（不决策）"),
    approve: str | None = typer.Option(None, "--approve", help="批准复核条目 ID（entry_id）"),
    reject: str | None = typer.Option(None, "--reject", help="拒绝复核条目 ID（entry_id）"),
) -> None:
    """处理人工复核队列：查看 / approve / reject。"""
    from sqlmodel import Session, select

    from reproagent.ingestion.review_queue import (
        confirm_manual_review,
        dequeue_manual_review,
    )
    from reproagent.persistence.tables import ManualReviewQueueTable

    if approve and reject:
        typer.echo("review: use only one of --approve / --reject", err=True)
        raise typer.Exit(code=1)

    repo = _build_repository()

    if approve:
        confirm_manual_review(approve, "approve", repo=repo)
        typer.echo(f"review: approved entry_id={approve}")
        return
    if reject:
        confirm_manual_review(reject, "reject", repo=repo)
        typer.echo(f"review: rejected entry_id={reject}")
        return

    # 列出或 peek 队首
    engine = repo.engine
    with Session(engine) as session:
        pending = session.exec(
            select(ManualReviewQueueTable)
            .where(ManualReviewQueueTable.status == "pending")
            .order_by(ManualReviewQueueTable.created_at)
        ).all()

    if not pending:
        typer.echo("review: queue empty")
        return

    typer.echo(f"review: {len(pending)} pending")
    for row in pending if list_queue else pending[:1]:
        typer.echo(
            f"  entry_id={row.id} report_id={row.report_id} "
            f"reason={row.reason} created_at={row.created_at}"
        )

    if list_queue:
        return

    item = dequeue_manual_review(repo=repo)
    if item is None:
        return
    entry_id, report, reason = item
    typer.echo(
        "review: head "
        f"entry_id={entry_id} report_id={report.id} "
        f"status={report.validation_status} reason={reason}"
    )
    typer.echo(f"  file_path={report.file_path}")
    typer.echo(f"  file_hash={report.file_hash}")
    if report.validation_errors:
        typer.echo(f"  errors={report.validation_errors}")
    typer.echo(
        "  decide: reproagent review --approve "
        f"{entry_id}  |  reproagent review --reject {entry_id}"
    )


@app.command()
def tui() -> None:
    """启动 TUI。"""
    from reproagent.tui.app import ReproAgentApp

    ReproAgentApp().run()


@app.command()
def benchmark(
    list_reports: bool = typer.Option(False, "--list", "-l", help="列出所有基准报告及其状态"),
    run: str | None = typer.Option(None, "--run", help="对指定报告（report_id）运行全链路比对"),
    run_all: bool = typer.Option(False, "--run-all", help="对所有非 pending 报告运行全链路比对"),
    report: bool = typer.Option(False, "--report", help="生成汇总 Markdown 报告"),
) -> None:
    """基准验证：复现准确率评估。"""
    from pathlib import Path

    import yaml

    benchmark_dir = (
        Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "benchmark"
    )
    catalog_path = benchmark_dir / "catalog.yaml"

    if not catalog_path.exists():
        typer.echo("benchmark: catalog.yaml not found", err=True)
        raise typer.Exit(code=1)

    with open(catalog_path) as f:
        catalog = yaml.safe_load(f)
    reports = catalog.get("reports", [])

    if list_reports:
        if not reports:
            typer.echo("benchmark: no reports in catalog")
            return
        typer.echo(f"{'report_id':<30} {'status':<12} {'broker':<16} {'title'}")
        typer.echo("-" * 90)
        for r in reports:
            title = r.get("report_title", "")[:40]
            typer.echo(
                f"{r['report_id']:<30} "
                f"{r.get('status', 'pending'):<12} "
                f"{r.get('broker', '?'):<16} "
                f"{title}"
            )
        return

    if report:
        typer.echo("# Benchmark Report")
        typer.echo()
        total = len(reports)
        ready = len([r for r in reports if r.get("status") != "pending"])
        annotated = len([r for r in reports if r.get("status") == "validated"])
        typer.echo(f"- Total reports: {total}")
        typer.echo(f"- Annotated (non-pending): {ready}")
        typer.echo(f"- Validated: {annotated}")
        typer.echo(f"- Pending annotation: {total - ready}")
        typer.echo()
        if annotated > 0:
            typer.echo("## Validated Reports")
            for r in reports:
                if r.get("status") == "validated":
                    typer.echo(f"- **{r['report_id']}**: {r.get('report_title', '')}")
        return

    if run:
        gt_path = benchmark_dir / run / "ground_truth.yaml"
        if not gt_path.exists():
            typer.echo(f"benchmark: {run} has no ground_truth.yaml", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"benchmark: running {run}")
        typer.echo(f"  ground_truth: {gt_path}")
        typer.echo("  (全链路比对待实现 — 当前仅校验 schema)")
        # TODO: 全链路流程
        return

    if run_all:
        ready = [r for r in reports if r.get("status") != "pending"]
        if not ready:
            typer.echo("benchmark: all reports are pending (not yet annotated)")
            return
        typer.echo(f"benchmark: running {len(ready)} report(s)")
        for r in ready:
            typer.echo(f"  {r['report_id']} ... (全链路待实现)")
        return

    # 默认行为: 显示摘要
    ready = [r for r in reports if r.get("status") != "pending"]
    typer.echo(
        f"benchmark: {len(reports)} total, {ready} ready, "
        f"{len(reports) - len(ready)} pending annotation"
    )
    typer.echo("Use --list to see all reports, --run REPORT_ID to execute")


@app.command()
def mcp() -> None:
    """启动 MCP 服务器（供 Claude Code 等 AI Agent 调用）。"""
    try:
        from reproagent.mcp_server import build_mcp_server

        server = build_mcp_server()
        server.run()
    except ImportError as e:
        typer.echo(f"MCP server unavailable: {e}", err=True)
        typer.echo("Install with: pip install fastmcp", err=True)
        raise typer.Exit(code=1)
