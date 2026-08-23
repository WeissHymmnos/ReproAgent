"""研报复现页：输入路径 → 触发复现 → 显示结果。"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, ProgressBar

from reproagent.settings import get_settings
from reproagent.tui.widgets.deviation_gauge import DeviationGauge
from reproagent.tui.widgets.log_panel import LogPanel


def parse_stage_banner(settings: object) -> str:
    """Honest parse-stage line: do not claim OCR/LLM backends that are off."""
    key = ""
    try:
        secret = getattr(settings, "llm_api_key", None)
        if secret is not None:
            key = secret.get_secret_value().strip()
    except Exception:  # noqa: BLE001
        key = ""
    mock = bool(getattr(settings, "mock_llm_allowed", True)) and not key
    if mock:
        return "解析中（离线 mock 提取，未调用 OCR / 外部 LLM）..."
    backend = getattr(settings, "finpdfpro_vlm_backend", "none") or "none"
    return f"解析中（parser={getattr(settings, 'parser_backend', 'finpdfpro')}, vlm={backend}）..."


def metrics_for_gauge(outcome: dict | None) -> dict[str, float]:
    """Numeric factor metrics for the TUI deviation panel."""
    factors = (outcome or {}).get("factors") or []
    if not factors or not isinstance(factors[0], dict):
        return {}
    raw = factors[0].get("metrics") or {}
    out: dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and number not in (float("inf"), float("-inf")):
            out[str(key)] = number
    return out


def reproduce_input_error(raw: str) -> str | None:
    """Validate a TUI/CLI reproduce path before starting the pipeline."""
    text = (raw or "").strip()
    if not text:
        return "请输入 PDF 路径。"
    path = Path(text).expanduser()
    if not path.exists():
        return f"路径不存在: {path}"
    if not path.is_file():
        return f"路径不是文件: {path}"
    return None


def review_enqueued_banner(outcome: dict | None) -> str:
    """Honest review-queue line; do not claim reflection when the gate was elsewhere."""
    reason = str((outcome or {}).get("reflection_status") or "").strip()
    if reason in {"", "None"}:
        reason = "review"
    return f"复现完毕，已送入人工复核（{reason}）。"


class ReportReproductionScreen(Vertical):
    """上传 PDF / 输入路径 → 触发复现 → 显示进度和结果。"""

    DEFAULT_CSS = """
    ReportReproductionScreen { padding: 1 2; }
    ReportReproductionScreen #title { text-style: bold; margin-bottom: 1; }
    ReportReproductionScreen #repro-input { margin-bottom: 1; }
    ReportReproductionScreen #repro-run { margin-bottom: 1; }
    ReportReproductionScreen #gauge-container { margin-bottom: 1; display: none; }
    ReportReproductionScreen #deviation-gauge { margin-bottom: 1; }
    ReportReproductionScreen #repro-log { border: round $primary; height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("研报复现", id="title")
        yield Input(placeholder="PDF 路径（绝对或相对）", id="repro-input")
        yield Button("运行复现", id="repro-run", variant="primary")

        with Vertical(id="gauge-container"):
            yield Label("复现逼真度 (Deviation Score)", id="gauge-label")
            yield ProgressBar(total=100, show_eta=False, id="deviation-gauge")
            yield DeviationGauge(id="dev-metrics")

        yield LogPanel(id="repro-log", wrap=True, highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repro-run":
            self._run_reproduce()

    def _run_reproduce(self) -> None:
        input_widget = self.query_one("#repro-input", Input)
        log = self.query_one("#repro-log", LogPanel)
        gauge_container = self.query_one("#gauge-container", Vertical)
        gauge = self.query_one("#deviation-gauge", ProgressBar)

        raw = (input_widget.value or "").strip()
        err = reproduce_input_error(raw)
        if err:
            log.write(f"[bold red]{err}[/]")
            return

        pdf_path = Path(raw).expanduser()

        log.clear()
        log.write(f"[bold green]开始复现:[/] {pdf_path.name}")

        gauge_container.styles.display = "block"
        gauge.progress = 0

        self.run_worker(self._reproduce_task(pdf_path), exclusive=True)

    async def _reproduce_task(self, pdf_path: Path) -> None:
        import anyio

        from reproagent.pipeline import reproduce_report

        log = self.query_one("#repro-log", LogPanel)
        gauge = self.query_one("#deviation-gauge", ProgressBar)

        settings = get_settings()

        # 模拟进度条加载
        gauge.advance(10)
        log.write("正在上传并校验...")
        await anyio.sleep(0.5)
        gauge.advance(20)
        log.write(parse_stage_banner(settings))

        try:
            # 真实复现
            outcome = await anyio.to_thread.run_sync(reproduce_report, pdf_path, settings)

            gauge.advance(40)
            log.write("解析与初步回测完成，开始分析指标偏差...")

        except NotImplementedError as exc:
            log.write(f"[bold red]pipeline 未实现:[/] {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            log.write(f"[bold red]复现失败:[/] {exc}")
            gauge.progress = 0
            return

        # 根据结果调整进度条
        nums = metrics_for_gauge(outcome if isinstance(outcome, dict) else None)
        if nums:
            self.query_one("#dev-metrics", DeviationGauge).set_deviations(nums)

        status = (outcome or {}).get("status")
        if status in ("passed", "converged", "success"):
            gauge.update(progress=100)
            log.write("[bold green]✓ 复现成功，因子已自动入库。[/]")
        elif status == "review_enqueued":
            gauge.update(progress=45)
            log.write(f"[bold yellow]⚠ {review_enqueued_banner(outcome)}[/]")
        else:
            gauge.update(progress=100)
            log.write(f"复现完成 ✓（status={status}）")

        if outcome:
            from reproagent.utils.jsonutil import dumps as json_dumps

            log.write(f"\n[dim]Pipeline 返回详情: {json_dumps(outcome)}[/]")
