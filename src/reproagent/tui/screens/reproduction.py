"""研报复现页：输入路径 → 触发复现 → 显示结果。"""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, ProgressBar, RichLog

from reproagent.settings import get_settings


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
            
        yield RichLog(id="repro-log", wrap=True, highlight=True, markup=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repro-run":
            self._run_reproduce()

    def _run_reproduce(self) -> None:
        input_widget = self.query_one("#repro-input", Input)
        log = self.query_one("#repro-log", RichLog)
        gauge_container = self.query_one("#gauge-container", Vertical)
        gauge = self.query_one("#deviation-gauge", ProgressBar)
        
        raw = (input_widget.value or "").strip()
        if not raw:
            log.write("[bold red]请输入 PDF 路径。[/]")
            return

        pdf_path = Path(raw).expanduser()
        if not pdf_path.exists():
            log.write(f"[bold red]路径不存在:[/] {pdf_path}")
            return

        log.clear()
        log.write(f"[bold green]开始复现:[/] {pdf_path.name}")

        gauge_container.styles.display = "block"
        gauge.progress = 0

        self.run_worker(self._reproduce_task(pdf_path), exclusive=True)

    async def _reproduce_task(self, pdf_path: Path) -> None:
        import anyio

        from reproagent.pipeline import reproduce_report

        log = self.query_one("#repro-log", RichLog)
        gauge = self.query_one("#deviation-gauge", ProgressBar)
        
        settings = get_settings()
        
        # 模拟进度条加载
        gauge.advance(10)
        log.write("正在上传并校验...")
        await anyio.sleep(0.5)
        gauge.advance(20)
        log.write("启动多模态解析 (PaddleOCR + DeepSeek)...")
        
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
        status = (outcome or {}).get("status")
        if status in ("passed", "converged", "success"):
            gauge.update(progress=100)
            log.write("[bold green]✓ 复现成功，因子已自动入库。[/]")
        elif status == "review_enqueued":
            gauge.update(progress=45)
            log.write(
                "[bold yellow]⚠ 复现完毕，但指标偏差过大，"
                "已触发 Reflection Loop 尝试修复。[/]"
            )
            log.write(
                "[bold yellow]⚠ Reflection 未收敛，因子已送入人工复核队列。[/]"
            )
        else:
            gauge.update(progress=100)
            log.write(f"复现完成 ✓（status={status}）")

        if outcome:
            log.write(
                f"\n[dim]Pipeline 返回详情: "
                f"{json.dumps(outcome, ensure_ascii=False)}[/]"
            )