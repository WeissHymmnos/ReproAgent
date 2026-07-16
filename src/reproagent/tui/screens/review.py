"""人工复核页面：显示队列计数与队首项。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Label, Static


class ManualReviewScreen(Static):
    """列出人工复核队列，支持 approve/reject。"""

    DEFAULT_CSS = """
    ManualReviewScreen { padding: 1 2; }
    ManualReviewScreen #title { text-style: bold; margin-bottom: 1; }
    ManualReviewScreen #review-refresh { margin-bottom: 1; }
    ManualReviewScreen #review-status { border: round $primary; padding: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("人工复核", id="title")
            yield Button("刷新队列", id="review-refresh", variant="primary")
            yield Static("点击刷新加载复核队列…", id="review-status")

    def on_mount(self) -> None:
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "review-refresh":
            self._refresh()

    def _refresh(self) -> None:
        status = self.query_one("#review-status", Static)
        status.update("加载中…")
        self.run_worker(self._load_task(), exclusive=True)

    async def _load_task(self) -> None:
        import anyio

        from reproagent.ingestion.review_queue import dequeue_manual_review
        from reproagent.persistence.db import get_engine, init_db
        from reproagent.persistence.repository import Repository
        from reproagent.settings import get_settings

        def _load() -> tuple[int, str | None]:
            settings = get_settings()
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            engine = get_engine(settings.db_path)
            init_db(engine)
            repo = Repository(engine)
            from sqlmodel import Session, select

            from reproagent.persistence.tables import ManualReviewQueueTable

            with Session(engine) as session:
                pending = session.exec(
                    select(ManualReviewQueueTable).where(
                        ManualReviewQueueTable.status == "pending"
                    )
                ).all()
                count = len(pending)
            item = dequeue_manual_review(repo=repo)
            return count, item

        status_widget = self.query_one("#review-status", Static)
        try:
            count, item = await anyio.to_thread.run_sync(_load)
        except Exception as exc:  # noqa: BLE001
            status_widget.update(f"加载失败: {exc}")
            return

        if count == 0:
            text = "复核队列为空（0 项待审）"
        else:
            text = f"队列待审: {count} 项\n"
            if item is not None:
                entry_id, report, reason = item
                text += (
                    f"队首: entry_id={entry_id}\n"
                    f"  report_id={report.id} status={report.validation_status}\n"
                    f"  reason={reason}"
                )
            else:
                text += "队首项无法解析（report 缺失）"
        status_widget.update(text)