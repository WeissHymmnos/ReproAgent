"""人工复核页面：显示队列并支持 approve/reject。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static


class ManualReviewScreen(Static):
    """列出人工复核队列，支持 approve/reject。"""

    DEFAULT_CSS = """
    ManualReviewScreen { padding: 1 2; }
    ManualReviewScreen #title { text-style: bold; margin-bottom: 1; }
    ManualReviewScreen #review-actions { height: auto; margin-bottom: 1; }
    ManualReviewScreen #review-actions Button { margin-right: 1; }
    ManualReviewScreen #review-status { border: round $primary; padding: 1; }
    """

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self._head_entry_id: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("人工复核", id="title")
            with Horizontal(id="review-actions"):
                yield Button("刷新队列", id="review-refresh", variant="primary")
                yield Button("批准队首", id="review-approve", variant="success")
                yield Button("拒绝队首", id="review-reject", variant="error")
            yield Static("点击刷新加载复核队列…", id="review-status")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "review-refresh":
            self._refresh()
        elif event.button.id == "review-approve":
            self._decide("approve")
        elif event.button.id == "review-reject":
            self._decide("reject")

    def _refresh(self) -> None:
        status = self.query_one("#review-status", Static)
        status.update("加载中…")
        self.run_worker(self._load_task(), exclusive=True)

    def _decide(self, decision: str) -> None:
        status = self.query_one("#review-status", Static)
        if not self._head_entry_id:
            status.update("无待审队首，请先刷新。")
            return
        status.update(f"处理中（{decision}）…")
        self.run_worker(self._decide_task(decision), exclusive=True)

    async def _load_task(self) -> None:
        import anyio

        from reproagent.ingestion.review_queue import dequeue_manual_review
        from reproagent.persistence.db import get_engine, init_db
        from reproagent.persistence.repository import Repository
        from reproagent.settings import get_settings

        def _load() -> tuple[int, str, str | None]:
            from sqlmodel import Session, select

            from reproagent.models.report import ResearchReport
            from reproagent.persistence.tables import ManualReviewQueueTable

            settings = get_settings()
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            engine = get_engine(settings.db_path)
            init_db(engine)
            repo = Repository(engine)

            with Session(engine) as session:
                pending = session.exec(
                    select(ManualReviewQueueTable).where(
                        ManualReviewQueueTable.status == "pending"
                    )
                ).all()
                count = len(pending)

            if count == 0:
                return 0, "复核队列为空（0 项待审）", None

            item = dequeue_manual_review(repo=repo)
            text = f"队列待审: {count} 项\n"
            head_id: str | None = None
            if item is not None:
                entry_id, report, reason = item
                assert isinstance(report, ResearchReport)
                head_id = entry_id
                text += (
                    f"队首: entry_id={entry_id}\n"
                    f"  report_id={report.id} status={report.validation_status}\n"
                    f"  reason={reason}\n"
                    "使用「批准队首」/「拒绝队首」完成决策。"
                )
            else:
                text += "队首项无法解析（report 缺失）"
            return count, text, head_id

        status_widget = self.query_one("#review-status", Static)
        try:
            _count, text, head_id = await anyio.to_thread.run_sync(_load)
        except Exception as exc:  # noqa: BLE001
            status_widget.update(f"加载失败: {exc}")
            return

        self._head_entry_id = head_id
        status_widget.update(text)

    async def _decide_task(self, decision: str) -> None:
        import anyio

        from reproagent.ingestion.review_queue import confirm_manual_review
        from reproagent.persistence.db import get_engine, init_db
        from reproagent.persistence.repository import Repository
        from reproagent.settings import get_settings

        entry_id = self._head_entry_id
        status_widget = self.query_one("#review-status", Static)
        if not entry_id:
            status_widget.update("无待审队首。")
            return

        def _apply() -> None:
            settings = get_settings()
            engine = get_engine(settings.db_path)
            init_db(engine)
            repo = Repository(engine)
            confirm_manual_review(entry_id, decision, repo=repo)  # type: ignore[arg-type]

        try:
            await anyio.to_thread.run_sync(_apply)
        except Exception as exc:  # noqa: BLE001
            status_widget.update(f"决策失败: {exc}")
            return

        self._head_entry_id = None
        status_widget.update(f"已 {decision} entry_id={entry_id}，正在刷新…")
        self._refresh()
