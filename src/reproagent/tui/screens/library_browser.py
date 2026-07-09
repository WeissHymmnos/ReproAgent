"""因子库浏览器。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static


class FactorLibraryScreen(Static):
    """树视图浏览因子库，右侧显示指标和图表。"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("因子库", id="title")
            yield Label("TODO: FactorTree + 指标面板", id="placeholder")
