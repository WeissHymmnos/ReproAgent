"""研报复现页：输入路径 → 触发复现 → 显示结果。"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, Static

from reproagent.settings import get_settings


class ReportReproductionScreen(Static):
    """上传 PDF / 输入路径 → 触发复现 → 显示进度和结果。"""

    DEFAULT_CSS = """
    ReportReproductionScreen { padding: 1 2; }
    ReportReproductionScreen #title { text-style: bold; margin-bottom: 1; }
    ReportReproductionScreen #repro-input { margin-bottom: 1; }
    ReportReproductionScreen #repro-run { margin-bottom: 1; }
    ReportReproductionScreen #repro-result { border: round $primary; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("研报复现", id="title")
            yield Input(placeholder="PDF 路径（绝对或相对）", id="repro-input")
            yield Button("运行复现", id="repro-run", variant="primary")
            yield Static("等待输入…", id="repro-result")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "repro-run":
            self._run_reproduce()

    def _run_reproduce(self) -> None:
        input_widget = self.query_one("#repro-input", Input)
        result = self.query_one("#repro-result", Static)
        raw = (input_widget.value or "").strip()
        if not raw:
            result.update("请输入 PDF 路径")
            return
        pdf_path = Path(raw).expanduser()
        if not pdf_path.exists():
            result.update(f"路径不存在: {pdf_path}")
            return
        result.update(f"开始复现 {pdf_path.name} …")
        self.run_worker(self._reproduce_task(pdf_path), exclusive=True)

    async def _reproduce_task(self, pdf_path: Path) -> None:
        import anyio

        from reproagent.pipeline import reproduce_report

        result_widget = self.query_one("#repro-result", Static)
        settings = get_settings()
        try:
            outcome = await anyio.to_thread.run_sync(reproduce_report, pdf_path, settings)
        except NotImplementedError as exc:
            result_widget.update(f"pipeline 未实现: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            result_widget.update(f"复现失败: {exc}")
            return
        result_widget.update(f"复现完成 ✓\n{outcome if outcome is not None else ''}")