"""因子库浏览器：列出已入库因子。"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Label, Markdown, Static, Tree

from reproagent.models.library import FactorLibraryEntry


class FactorLibraryScreen(Static):
    """树视图浏览因子库，右侧显示指标和图表。"""

    DEFAULT_CSS = """
    FactorLibraryScreen { padding: 1 2; }
    FactorLibraryScreen #title { text-style: bold; margin-bottom: 1; }
    FactorLibraryScreen #lib-refresh { margin-bottom: 1; }
    FactorLibraryScreen Horizontal { height: 1fr; margin-top: 1; }
    FactorLibraryScreen Tree { width: 30%; border: round $primary; }
    FactorLibraryScreen VerticalScroll { width: 70%; border: round $secondary; padding: 1 2; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entries: dict[str, FactorLibraryEntry] = {}

    def compose(self) -> ComposeResult:
        yield Label("因子库", id="title")
        yield Button("刷新", id="lib-refresh", variant="primary")
        with Horizontal():
            yield Tree("所有因子", id="factor-tree")
            with VerticalScroll():
                yield Markdown("← 请在左侧选择一个因子以查看详情", id="factor-detail")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lib-refresh":
            self._refresh()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """当用户点击树节点时，如果是一个具体的因子，则在右侧显示详情。"""
        node_id = event.node.data
        detail = self.query_one("#factor-detail", Markdown)
        if node_id and node_id in self.entries:
            entry = self.entries[node_id]
            md = f"# {entry.factor.name} ({entry.factor.name_cn or entry.factor.name})\n\n"
            md += f"**状态**: {entry.status} | **风格**: {entry.factor.style} | **版本**: v{entry.version}\n\n"
            md += f"### 公式\n```math\n{entry.factor.formula}\n```\n\n"
            md += f"### 描述\n{entry.factor.description}\n\n"
            if entry.backtest_metrics:
                md += "### 回测指标\n"
                md += f"- **IC Mean**: {entry.backtest_metrics.ic_mean:.4f}\n"
                md += f"- **IC IR**: {entry.backtest_metrics.ic_ir:.4f}\n"
                md += f"- **多空收益**: {entry.backtest_metrics.long_short_return:.4f}\n"
                md += f"- **夏普比率**: {entry.backtest_metrics.sharpe_ratio:.4f}\n"
                md += f"- **换手率**: {entry.backtest_metrics.turnover:.4f}\n"
            
            detail.update(md)
        else:
            detail.update("← 请在左侧选择一个因子以查看详情")

    def _refresh(self) -> None:
        tree = self.query_one("#factor-tree", Tree)
        tree.root.collapse()
        tree.clear()
        detail = self.query_one("#factor-detail", Markdown)
        detail.update("加载中…")
        self.run_worker(self._load_task(), exclusive=True)

    async def _load_task(self) -> None:
        import anyio

        from reproagent.library.manager import FactorLibraryManager
        from reproagent.persistence.db import get_engine, init_db
        from reproagent.persistence.paths import AppPaths
        from reproagent.settings import get_settings

        def _load() -> list[FactorLibraryEntry]:
            settings = get_settings()
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            engine = get_engine(settings.db_path)
            init_db(engine)
            from reproagent.persistence.repository import Repository

            repo = Repository(engine)
            paths = AppPaths.from_settings(settings)
            paths.ensure_layout()
            manager = FactorLibraryManager(repository=repo, paths=paths)
            return manager.list()

        try:
            entries = await anyio.to_thread.run_sync(_load)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#factor-detail", Markdown).update(f"加载失败: {exc}")
            return

        self.entries = {e.id: e for e in entries}
        tree = self.query_one("#factor-tree", Tree)
        tree.clear()
        
        # 按 style 分组
        grouped = defaultdict(list)
        for e in entries:
            style = e.factor.style or "未分类"
            grouped[style].append(e)

        for style, style_entries in grouped.items():
            style_node = tree.root.add(f"📂 {style}", expand=True)
            for e in style_entries:
                style_node.add_leaf(f"📄 {e.factor.name}", data=e.id)
                
        tree.root.expand()

        if not entries:
            self.query_one("#factor-detail", Markdown).update("empty library（尚无因子入库）")
        else:
            self.query_one("#factor-detail", Markdown).update("← 请在左侧选择一个因子以查看详情")