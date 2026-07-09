"""流式 loguru 输出面板。"""

from __future__ import annotations

from textual.widgets import RichLog


class LogPanel(RichLog):
    """展示运行日志。"""

    def write_line(self, message: str) -> None:
        self.write(message)
