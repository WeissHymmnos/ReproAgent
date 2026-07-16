"""因子库浏览器：列出已入库因子。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Label, Static


class FactorLibraryScreen(Static):
    """树视图浏览因子库，右侧显示指标和图表。"""

    DEFAULT_CSS = """
    FactorLibraryScreen { padding: 1 2; }
    FactorLibraryScreen #title { text-style: bold; margin-bottom: 1; }
    FactorLibraryScreen #lib-refresh { margin-bottom: 1; }
    FactorLibraryScreen #lib-list { border: round $primary; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("因子库", id="title")
            yield Button("刷新", id="lib-refresh", variant="primary")
            yield Static("点击刷新加载因子库…", id="lib-list")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lib-refresh":
            self._refresh()

    def _refresh(self) -> None:
        list_widget = self.query_one("#lib-list", Static)
        list_widget.update("加载中…")
        self.run_worker(self._load_task(), exclusive=True)

    async def _load_task(self) -> None:
        import anyio

        from reproagent.library.manager import FactorLibraryManager
        from reproagent.persistence.db import get_engine, init_db
        from reproagent.persistence.paths import AppPaths
        from reproagent.settings import get_settings

        def _load() -> tuple[int, list[str]]:
            settings = get_settings()
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            engine = get_engine(settings.db_path)
            init_db(engine)
            from reproagent.persistence.repository import Repository

            repo = Repository(engine)
            paths = AppPaths.from_settings(settings)
            paths.ensure_layout()
            manager = FactorLibraryManager(repository=repo, paths=paths)
            entries = manager.list()
            lines = [
                f"{e.factor.name:<24} {e.factor.style:<12} {e.status:<10} v{e.version}"
                for e in entries
            ]
            return len(entries), lines

        list_widget = self.query_one("#lib-list", Static)
        try:
            count, lines = await anyio.to_thread.run_sync(_load)
        except Exception as exc:  # noqa: BLE001
            list_widget.update(f"加载失败: {exc}")
            return
        if count == 0:
            text = "empty library（尚无因子入库）"
        else:
            text = f"共 {count} 个因子：\n" + "\n".join(lines)
        list_widget.update(text)