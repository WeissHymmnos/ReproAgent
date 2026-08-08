"""loguru 配置：文件轮转 + stderr。"""

from __future__ import annotations

import sys

from loguru import logger

from reproagent.settings import Settings


def setup_logging(settings: Settings) -> None:
    """初始化 loguru：写入 logs_dir 并镜像到 stderr。"""
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        settings.logs_dir / "reproagent.log",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        level="DEBUG",
        format=("{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}"),
    )
    logger.add(sys.stderr, level="INFO")
