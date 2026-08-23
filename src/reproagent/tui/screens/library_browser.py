"""因子库浏览器：列出已入库因子。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, Markdown, Static, Tree

from reproagent.tui.widgets.factor_tree import FactorTree

from reproagent.models.library import FactorLibraryEntry

DEFAULT_TREE_LIMIT = 200


def select_library_entries_for_view(
    entries: list[FactorLibraryEntry],
    *,
    query: str | None = None,
    limit: int = DEFAULT_TREE_LIMIT,
) -> tuple[list[FactorLibraryEntry], int]:
    """Filter + cap library rows for the TUI tree (do not dump 1700 leaves)."""
    q = (query or "").strip().lower()
    if q:
        kept: list[FactorLibraryEntry] = []
        for entry in entries:
            factor = entry.factor
            hay = " ".join(
                [
                    factor.name or "",
                    factor.name_cn or "",
                    factor.formula or "",
                    str(factor.style or ""),
                ]
            ).lower()
            if q in hay:
                kept.append(entry)
        entries = kept
    total = len(entries)
    cap = None if int(limit) <= 0 else int(limit)
    shown = entries if cap is None else entries[:cap]
    return shown, total


def format_library_entry_md(entry: FactorLibraryEntry) -> str:
    """Markdown detail pane for a library entry (TUI)."""
    name_cn = entry.factor.name_cn or entry.factor.name
    md = f"# {entry.factor.name} ({name_cn})\n\n"
    md += (
        f"**状态**: {entry.status} | **风格**: {entry.factor.style} "
        f"| **版本**: v{entry.version}\n\n"
    )
    metrics = getattr(entry, "metrics", None) or {}
    if metrics:
        md += "### 回测指标\n"
        for key in ("ic", "icir", "sharpe", "ann_return", "max_drawdown", "turnover"):
            if key in metrics and not isinstance(metrics[key], list):
                md += f"- **{key}**: {metrics[key]}\n"
        md += "\n"
    md += f"### 公式\n```math\n{entry.factor.formula}\n```\n\n"
    md += "### 输入字段\n"
    if entry.factor.input_fields:
        md += ", ".join(f"`{f}`" for f in entry.factor.input_fields) + "\n\n"
    else:
        md += "（无）\n\n"
    md += "### 元数据\n"
    md += f"- **report_id**: `{entry.report_id}`\n"
    md += f"- **universe**: {entry.factor.universe}\n"
    md += f"- **rebalance**: {entry.factor.rebalance_frequency}\n"
    md += f"- **dedup_hash**: `{entry.dedup_hash[:16]}…`\n"
    md += f"- **backtest_result_id**: `{entry.backtest_result_id}`\n"
    md += f"- **deviation_passed**: {entry.deviation_passed}\n"
    if entry.tags:
        md += f"- **tags**: {', '.join(entry.tags)}\n"
    return md


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
        yield Input(placeholder="搜索名称 / 公式 / 风格", id="lib-query")
        yield Button("刷新", id="lib-refresh", variant="primary")
        with Horizontal():
            yield FactorTree("所有因子", id="factor-tree")
            with VerticalScroll():
                yield Markdown("← 请在左侧选择一个因子以查看详情", id="factor-detail")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lib-refresh":
            self._refresh()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "lib-query":
            self._refresh()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """当用户点击树节点时，如果是一个具体的因子，则在右侧显示详情。"""
        node_id = event.node.data
        detail = self.query_one("#factor-detail", Markdown)
        if node_id and node_id in self.entries:
            detail.update(format_library_entry_md(self.entries[node_id]))
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

        query = ""
        try:
            query = (self.query_one("#lib-query", Input).value or "").strip()
        except Exception:  # noqa: BLE001
            query = ""

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
            loaded = await anyio.to_thread.run_sync(_load)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#factor-detail", Markdown).update(f"加载失败: {exc}")
            return

        entries, total = select_library_entries_for_view(loaded, query=query)
        self.entries = {e.id: e for e in entries}
        tree = self.query_one("#factor-tree", Tree)
        tree.clear()

        # 按 style 分组
        grouped: dict[str, list[FactorLibraryEntry]] = defaultdict(list)
        for e in entries:
            style: str = str(e.factor.style) if e.factor.style else "未分类"
            grouped[style].append(e)

        for style, style_entries in grouped.items():
            style_node = tree.root.add(f"📂 {style}", expand=True)
            for e in style_entries:
                style_node.add_leaf(f"📄 {e.factor.name}", data=e.id)

        tree.root.expand()

        detail = self.query_one("#factor-detail", Markdown)
        if not loaded:
            detail.update("empty library（尚无因子入库）")
        elif total > len(entries):
            detail.update(
                f"显示 {len(entries)} / {total} 条（搜索或提高匹配以缩小范围）。\n"
                "← 请在左侧选择一个因子以查看详情"
            )
        else:
            detail.update(f"{total} 条。← 请在左侧选择一个因子以查看详情")
