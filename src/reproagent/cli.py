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


def review_reason_bucket(reason: str) -> str:
    """Collapse per-factor review reasons so `--stats` is readable."""
    r = (reason or "").strip()
    if not r:
        return "(empty)"
    if r.startswith("No factors extracted"):
        return "No factors extracted"
    if r.startswith("Reflection failed"):
        return "Reflection failed"
    if r.startswith("Strict mode"):
        return "Strict mode"
    if r.startswith("Factor ") and " failed" in r:
        return "Factor failed"
    if r.startswith("Confidence gate"):
        return "Confidence gate"
    if ":" in r:
        return r.split(":", 1)[0].strip()
    return r[:80]


def summarize_review_queue(pending: list[Any]) -> str:
    """Human summary: count, age range, reason buckets."""
    from collections import Counter

    from reproagent.ingestion.review_queue import review_capability_kind

    if not pending:
        return "review: queue empty"
    buckets = Counter(review_reason_bucket(getattr(row, "reason", "") or "") for row in pending)
    capability_n = sum(
        1 for row in pending if review_capability_kind(getattr(row, "reason", "") or "")
    )
    human_n = len(pending) - capability_n
    lines = [
        f"review: {len(pending)} pending ({human_n} human, {capability_n} capability)"
    ]
    created = [getattr(row, "created_at", None) for row in pending]
    created = [c for c in created if c]
    if created:
        lines.append(f"  oldest: {min(created)}")
        lines.append(f"  newest: {max(created)}")
    for bucket, n in buckets.most_common():
        lines.append(f"  {n:4d}  {bucket}")
    return "\n".join(lines)


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


def echo_pipeline_cli(kind: str, result: Any) -> None:
    """Print JSON; EXIT 0 for passed/partial/converged/soft_passed."""
    status = None
    if isinstance(result, dict):
        status = result.get("status")
    if result is not None:
        try:
            from reproagent.utils.jsonutil import dumps as json_dumps

            typer.echo(json_dumps(result))
        except Exception:  # noqa: BLE001
            typer.echo(str(result))
    if status in {"passed", "partial", "converged", "soft_passed"}:
        typer.echo(f"{kind} ok (status={status})")
        return
    if status == "review_enqueued":
        typer.echo(f"{kind} review_enqueued")
        return
    typer.echo(f"{kind} failed: status={status or 'unknown'}", err=True)
    raise typer.Exit(code=1)


def _build_repository() -> Any:
    """构造一个默认 Repository（初始化 DB）。"""
    from reproagent.persistence.db import get_engine, init_db
    from reproagent.persistence.repository import Repository

    settings = get_settings()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        from reproagent.exceptions import ConfigurationError

        raise ConfigurationError(
            f"data_dir is not writable: {settings.data_dir} — "
            "fix permissions or point DATA_DIR at a writable location"
        ) from exc
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
    from reproagent.exceptions import ValidationError
    from reproagent.ingestion.uploader import upload_pdf
    from reproagent.ingestion.validator import validate_pdf

    try:
        report = upload_pdf(pdf_path)
    except (ValidationError, FileNotFoundError, OSError) as exc:
        typer.echo(f"ingest failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    report = validate_pdf(report)

    repo = _build_repository()
    existing = repo.get_report_by_hash(report.file_hash)

    if report.validation_status == "invalid":
        typer.echo(
            f"ingest failed: validation_status=invalid errors={report.validation_errors}",
            err=True,
        )
        if existing is None:
            try:
                repo.save_report(report)
                from reproagent.ingestion.review_queue import enqueue_manual_review

                enqueue_manual_review(report, "validation_failed", repo=repo)
            except Exception as exc:  # noqa: BLE001
                typer.echo(f"warn: could not enqueue review: {exc}", err=True)
        raise typer.Exit(code=1)

    if existing is not None:
        typer.echo(
            "ingest ok: "
            f"id={existing.id} hash={existing.file_hash[:12]}… "
            f"status={existing.validation_status} pages={existing.page_count} "
            "(already ingested)"
        )
        return

    repo.save_report(report)

    typer.echo(
        "ingest ok: "
        f"id={report.id} hash={report.file_hash[:12]}… "
        f"status={report.validation_status} pages={report.page_count}"
    )


@app.command()
def reproduce(
    pdf_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        help="PDF 或 Markdown / 纯文本路径",
    ),
) -> None:
    """端到端：摄入 → 解析 → 复现 → 偏差 → 入库。

    `.md` / `.txt` 走 text 路径（跳过 PDF 解析）。
    """
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

    echo_pipeline_cli("reproduce", result)


@app.command()
def text(
    file: Path | None = typer.Option(
        None, "--file", "-f", exists=True, dir_okay=False, help="Markdown 文件路径"
    ),
    title: str = typer.Option(
        "Markdown Input", "--title", "-t", help="研报标题"
    ),
    broker: str = typer.Option(
        "unknown", "--broker", "-b", help="券商名称"
    ),
) -> None:
    """从 Markdown 文本直接提取因子并复现（跳过 PDF 解析）。

    支持两种输入方式：
    1. --file/-f 指定 Markdown 文件路径
    2. 无参数时从 stdin 读取（支持管道输入）

    示例:
      reproagent text --file research_report.md
      cat report.md | reproagent text
      reproagent text --title "动量因子研报" --broker "中信证券" < report.md
    """
    import sys

    try:
        from reproagent.pipeline import reproduce_text
    except ImportError as exc:
        typer.echo(f"text unavailable: pipeline import failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # 读取输入
    if file is not None:
        try:
            text_content = file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.echo(f"text failed: not UTF-8 text: {file}", err=True)
            raise typer.Exit(code=1) from exc
    elif not sys.stdin.isatty():
        text_content = sys.stdin.read()
    else:
        typer.echo(
            "text: 请通过 --file 指定文件，或通过管道传入 Markdown 内容。",
            err=True,
        )
        raise typer.Exit(code=1)

    if not text_content.strip():
        typer.echo("text: 输入为空。", err=True)
        raise typer.Exit(code=1)

    settings = get_settings()
    if settings.is_prod and not settings.mock_llm_allowed:
        key = settings.llm_api_key.get_secret_value().strip()
        if not key:
            typer.echo(
                "text failed: APP_ENV=prod requires LLM_API_KEY "
                "(or set ALLOW_MOCK_LLM=true for offline).",
                err=True,
            )
            raise typer.Exit(code=1)

    typer.echo(f"text: processing {len(text_content)} chars, title={title!r}")

    try:
        result = reproduce_text(text_content, settings, title=title, broker=broker)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"text failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    echo_pipeline_cli("text", result)


@app.command()
def library(
    style: str | None = typer.Option(None, "--style", "-s", help="按风格过滤"),
    query: str | None = typer.Option(None, "--query", "-q", help="按名称 / 公式搜索"),
    limit: int = typer.Option(50, "--limit", help="最多打印条数；0 表示不截断"),
    html: bool = typer.Option(False, "--html", help="生成 HTML 仪表盘到 wiki_dir"),
    refresh_metrics: bool = typer.Option(
        False, "--refresh-metrics", help="从 backtest/ 产物回填空 metrics"
    ),
) -> None:
    """浏览因子库。"""
    from reproagent.models.library import LibraryFilter

    manager = _build_library_manager()
    if refresh_metrics:
        settings = get_settings()
        n = manager.backfill_metrics(settings.data_dir)
        typer.echo(f"library: refreshed metrics for {n} factor(s)")
        # Wiki dashboard is a static file; backfill must rewrite it or IC stays 0.
        full = manager.list()
        if full:
            from reproagent.library.dashboard import write_library_dashboard

            out = settings.wiki_dir / "dashboard.html"
            write_library_dashboard(full, out)
            typer.echo(f"html dashboard -> {out}")
    filter_ = LibraryFilter(style=style) if style else None
    all_entries = manager.list(filter_, query=query)
    cap = None if int(limit) == 0 else max(1, int(limit))
    entries = all_entries if cap is None else all_entries[:cap]

    if not all_entries:
        typer.echo("library: empty (0 factors)")
        if html:
            typer.echo("--html requested but library empty; skipping dashboard")
        return

    if cap is not None and len(all_entries) > len(entries):
        typer.echo(f"library: {len(all_entries)} factor(s), showing first {len(entries)}")
    else:
        typer.echo(f"library: {len(entries)} factor(s)")
    typer.echo(f"{'id':<34} {'name':<24} {'style':<12} {'status':<10} {'version':<10}")
    typer.echo("-" * 96)
    for entry in entries:
        typer.echo(
            f"{entry.id:<34} {entry.factor.name:<24} {entry.factor.style:<12} "
            f"{entry.status:<10} {entry.version:<10}"
        )

    if html:
        from reproagent.library.dashboard import write_library_dashboard

        settings = get_settings()
        out = settings.wiki_dir / "dashboard.html"
        write_library_dashboard(all_entries, out)
        if cap is not None and len(all_entries) > len(entries):
            typer.echo(
                f"html dashboard uses all {len(all_entries)} matched factors "
                f"(print cap is {cap})"
            )
        typer.echo(f"html dashboard -> {out}")


@app.command()
def review(
    list_queue: bool = typer.Option(False, "--list", "-l", help="仅列出待审项（不决策）"),
    approve: str | None = typer.Option(None, "--approve", help="批准复核条目 ID（entry_id）"),
    reject: str | None = typer.Option(None, "--reject", help="拒绝复核条目 ID（entry_id）"),
    dismiss_capability: bool = typer.Option(
        False,
        "--dismiss-capability",
        help="将系统能力失败（抽不出因子、数据源/wiki/公式引擎、反思耗尽等）标为 dismissed_capability，不 approve/reject",
    ),
    limit: int = typer.Option(50, "--limit", help="--list 最多打印条数"),
    stats: bool = typer.Option(False, "--stats", help="按原因分桶统计待审队列"),
    reason: str | None = typer.Option(
        None, "--reason", help="仅保留 reason 含子串的待审项"
    ),
    human_only: bool = typer.Option(
        False,
        "--human-only",
        help="--list / --stats / peek 只看需要人看的项",
    ),
) -> None:
    """处理人工复核队列：查看 / approve / reject / 清掉系统能力噪声。"""
    from sqlmodel import Session, select

    from reproagent.ingestion.review_queue import (
        confirm_manual_review,
        dequeue_manual_review,
        review_capability_kind,
    )
    from reproagent.persistence.tables import ManualReviewQueueTable

    exclusive = [bool(approve), bool(reject), bool(dismiss_capability)]
    if sum(exclusive) > 1:
        typer.echo(
            "review: use only one of --approve / --reject / --dismiss-capability",
            err=True,
        )
        raise typer.Exit(code=1)

    repo = _build_repository()

    if dismiss_capability:
        from reproagent.exceptions import PersistenceError

        try:
            result = repo.dismiss_capability_reviews()
        except PersistenceError as exc:
            typer.echo(f"review: dismiss-capability failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(
            "review: dismissed_capability "
            f"{result['dismissed']}  kept {result['kept']}  "
            f"scanned {result['scanned']}"
        )
        buckets = result.get("buckets") or {}
        for kind, n in sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0])):
            typer.echo(f"  {n:4d}  {kind}")
        return

    if approve:
        from reproagent.exceptions import PersistenceError

        try:
            confirm_manual_review(approve, "approve", repo=repo)
        except PersistenceError as exc:
            typer.echo(f"review: approve failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(f"review: approved entry_id={approve}")
        return
    if reject:
        from reproagent.exceptions import PersistenceError

        try:
            confirm_manual_review(reject, "reject", repo=repo)
        except PersistenceError as exc:
            typer.echo(f"review: reject failed: {exc}", err=True)
            raise typer.Exit(code=1) from exc
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

    if reason:
        needle = reason.lower()
        pending = [row for row in pending if needle in (row.reason or "").lower()]

    if human_only:
        pending = [
            row
            for row in pending
            if review_capability_kind(row.reason or "") is None
        ]

    if not pending:
        typer.echo("review: queue empty")
        return

    if stats:
        typer.echo(summarize_review_queue(pending))
        return

    if list_queue:
        typer.echo(f"review: {len(pending)} pending")
        cap = max(1, int(limit))
        if len(pending) > cap:
            typer.echo(f"review: showing first {cap} of {len(pending)}")
        for row in pending[:cap]:
            kind = review_capability_kind(row.reason or "")
            tag = "human" if kind is None else f"capability:{kind}"
            typer.echo(
                f"  [{tag}] entry_id={row.id} report_id={row.report_id} "
                f"reason={row.reason} created_at={row.created_at}"
            )
        return

    item = dequeue_manual_review(repo=repo)
    if item is None:
        typer.echo("review: queue empty")
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
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="绑定地址"),
    port: int = typer.Option(8765, "--port", "-p", help="端口"),
) -> None:
    """启动浏览器工作台（因子库 / 人工复核 / 研报复现）。"""
    from reproagent.web.app import serve as serve_web

    typer.echo(f"Starting ReproAgent workstation on http://{host}:{port}/")
    serve_web(host=host, port=port)


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
        settings = get_settings()
        results_root = settings.data_dir / "benchmark"
        typer.echo()
        typer.echo("## Last run results")
        found = False
        if results_root.is_dir():
            for r in reports:
                rid = r.get("report_id")
                if not rid:
                    continue
                path = results_root / str(rid) / "result.json"
                if not path.exists():
                    continue
                found = True
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    typer.echo(f"- **{rid}**: unreadable {path}")
                    continue
                summary = data.get("summary") or {}
                typer.echo(
                    f"- **{rid}**: status={data.get('status')} "
                    f"passed={summary.get('passed', 0)} "
                    f"failed={summary.get('failed', 0)} "
                    f"errors={summary.get('errors', 0)}"
                )
        if not found:
            typer.echo("- (no result.json yet; run --run or --run-all)")
        return

    if run:
        gt_path = benchmark_dir / run / "ground_truth.yaml"
        if not gt_path.exists():
            typer.echo(f"benchmark: {run} has no ground_truth.yaml", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"benchmark: running {run}")
        typer.echo(f"  ground_truth: {gt_path}")
        try:
            from reproagent.benchmark.runner import run_benchmark
        except ImportError as exc:
            typer.echo(f"benchmark unavailable: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        settings = get_settings()
        # 默认指向 fixtures 测试数据，便于离线跑通
        if settings.local_data_path is None:
            local = Path("tests/fixtures/test_data")
            if local.exists():
                settings = settings.model_copy(update={"local_data_path": local})

        result = run_benchmark(run, settings, benchmark_dir=benchmark_dir)
        from reproagent.utils.jsonutil import dumps as json_dumps

        typer.echo(json_dumps(result, indent=2))
        summary = result.get("summary") or {}
        if result.get("status") not in {"passed", "partial"}:
            raise typer.Exit(code=1)
        if summary.get("errors", 0) > 0 and summary.get("passed", 0) == 0:
            raise typer.Exit(code=1)
        return

    if run_all:
        ready = [r for r in reports if r.get("status") != "pending"]
        if not ready:
            typer.echo("benchmark: all reports are pending (not yet annotated)")
            return
        try:
            from reproagent.benchmark.runner import run_benchmark_all
        except ImportError as exc:
            typer.echo(f"benchmark unavailable: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        settings = get_settings()
        if settings.local_data_path is None:
            local = Path("tests/fixtures/test_data")
            if local.exists():
                settings = settings.model_copy(update={"local_data_path": local})

        typer.echo(f"benchmark: running {len(ready)} report(s)")
        result = run_benchmark_all(settings, benchmark_dir=benchmark_dir)
        from reproagent.utils.jsonutil import dumps as json_dumps

        typer.echo(json_dumps(result, indent=2))
        if result.get("status") == "error":
            raise typer.Exit(code=1)
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
        typer.echo("Install with: uv sync --extra mcp", err=True)
        raise typer.Exit(code=1)
