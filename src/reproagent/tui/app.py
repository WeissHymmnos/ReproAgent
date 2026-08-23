"""ReproAgent Textual 主应用。"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane


def tui_subtitle() -> str:
    """Build the header subtitle from the command catalog + key bindings."""
    from reproagent.tui.commands import COMMANDS

    keys = {"reproduce": "r", "library": "l", "review": "v"}
    parts = ["研报因子复现系统"]
    for spec in COMMANDS:
        key = keys.get(spec.id)
        if key:
            parts.append(f"{key} {spec.title}")
    parts.append("q 退出")
    return " · ".join(parts)


class ReproAgentApp(App[None]):
    """ReproAgent TUI 主应用。"""

    TITLE = "ReproAgent"
    SUB_TITLE = tui_subtitle()
    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("d", "toggle_dark", "深色/浅色"),
        Binding("r", "show_reproduce", "复现研报"),
        Binding("l", "show_library", "因子库"),
        Binding("v", "show_review", "人工复核"),
    ]

    def compose(self) -> ComposeResult:
        from reproagent.tui.screens.library_browser import FactorLibraryScreen
        from reproagent.tui.screens.reproduction import ReportReproductionScreen
        from reproagent.tui.screens.review import ManualReviewScreen

        yield Header()
        with TabbedContent():
            with TabPane("复现", id="tab-reproduce"):
                yield ReportReproductionScreen()
            with TabPane("因子库", id="tab-library"):
                yield FactorLibraryScreen()
            with TabPane("人工复核", id="tab-review"):
                yield ManualReviewScreen()
        yield Footer()

    def action_show_reproduce(self) -> None:
        self.query_one(TabbedContent).active = "tab-reproduce"

    def action_show_library(self) -> None:
        self.query_one(TabbedContent).active = "tab-library"

    def action_show_review(self) -> None:
        self.query_one(TabbedContent).active = "tab-review"
