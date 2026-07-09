"""人工复核页面。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static


class ManualReviewScreen(Static):
    """列出人工复核队列，支持 approve/reject。"""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("人工复核", id="title")
            yield Label("TODO: 队列列表 + approve/reject", id="placeholder")
