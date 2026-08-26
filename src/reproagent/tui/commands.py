"""TUI 页签标题。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    id: str
    title: str
    description: str


COMMANDS: list[CommandSpec] = [
    CommandSpec("ingest", "摄入研报", "上传 PDF 并校验"),
    CommandSpec("reproduce", "复现研报", "端到端复现流程"),
    CommandSpec("library", "打开因子库", "浏览已入库因子"),
    CommandSpec("review", "人工复核", "处理复核队列"),
]
