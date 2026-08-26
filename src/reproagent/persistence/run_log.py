"""reproduce / reflection 运行记录（JSON）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def runs_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_record(data_dir: Path, record: dict[str, Any]) -> Path:
    """写一条运行记录。缺 ``id`` / ``created_at`` 时补上。"""
    payload = dict(record)
    payload.setdefault("id", uuid4().hex)
    payload.setdefault("created_at", datetime.now(UTC).isoformat())
    dest = runs_dir(data_dir) / f"{payload['id']}.json"
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2),
        encoding="utf-8",
    )
    return dest


def list_run_records(data_dir: Path) -> list[dict[str, Any]]:
    root = Path(data_dir) / "runs"
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data.setdefault("id", path.stem)
            out.append(data)
    return out
