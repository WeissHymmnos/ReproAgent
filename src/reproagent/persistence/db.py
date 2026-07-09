"""SQLite engine / session 工厂。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, create_engine


def get_engine(db_path: Path, *, echo: bool = False) -> Any:
    """创建 SQLModel/SQLAlchemy engine。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{db_path}"
    return create_engine(url, echo=echo)


def init_db(engine: Any) -> None:
    """create_all 初始化表结构。"""
    # 导入表模块以注册 metadata
    from reproagent.persistence import tables as _tables  # noqa: F401

    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session(engine: Any) -> Iterator[Session]:
    """会话上下文管理器。"""
    with Session(engine) as session:
        yield session
