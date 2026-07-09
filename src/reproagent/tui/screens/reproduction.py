"""研报复现页。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static


class ReportReproductionScreen(Static):
    """上传 PDF / 输入路径 → 触发复现 → 显示进度和结果。"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("研报复现", id="title")
            yield Label("TODO: 路径输入、进度条、结果面板", id="placeholder")
