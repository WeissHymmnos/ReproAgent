"""SQLite engine / session 工厂。"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

_INIT_LOCK = threading.Lock()


def get_engine(db_path: Path, *, echo: bool = False) -> Any:
    """创建 SQLModel/SQLAlchemy engine。

    - ``check_same_thread=False``：允许跨线程使用（CLI / TUI / 后台任务）。
    - 启用 WAL journal_mode，提升并发读与崩溃恢复能力。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=echo, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_conn: Any, _record: Any) -> None:  # noqa: ANN401
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def init_db(engine: Any) -> None:
    """create_all 初始化表结构（进程内串行，防并发建表竞态）。"""
    with _INIT_LOCK:
        _init_db_locked(engine)


def _init_db_locked(engine: Any) -> None:
    # 导入表模块以注册 metadata
    from reproagent.persistence import tables as _tables  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _migrate_review_payload(engine)
    _migrate_library_metrics(engine)


def _migrate_review_payload(engine: Any) -> None:
    """Add payload_json to existing manual_review_queue rows."""
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(manual_review_queue)")).fetchall()
        cols = {row[1] for row in rows}
        if rows and "payload_json" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE manual_review_queue "
                    "ADD COLUMN payload_json VARCHAR DEFAULT '{}'"
                )
            )


def _migrate_library_metrics(engine: Any) -> None:
    """Add metrics_json to existing factor_library rows."""
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(factor_library)")).fetchall()
        cols = {row[1] for row in rows}
        if rows and "metrics_json" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE factor_library "
                    "ADD COLUMN metrics_json VARCHAR DEFAULT '{}'"
                )
            )


@contextmanager
def get_session(engine: Any) -> Iterator[Session]:
    """会话上下文管理器。"""
    with Session(engine) as session:
        yield session
