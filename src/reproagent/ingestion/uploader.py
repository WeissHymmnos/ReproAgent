"""PDF 上传 → ResearchReport。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from reproagent.exceptions import ValidationError
from reproagent.models.report import ResearchReport
from reproagent.utils.hashing import sha256_file
from reproagent.utils.pdf import get_page_count


def upload_pdf(file_path: Path) -> ResearchReport:
    """上传一篇 PDF → 创建 ResearchReport（file_hash + page_count 即时计算）。

    单篇支持；批量 for 循环调用即可。

    Raises:
        FileNotFoundError: 路径不存在。
        ValidationError: 路径不是文件。
    """
    resolved = Path(file_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not resolved.is_file():
        raise ValidationError(f"Path is not a file: {file_path}")

    file_hash = sha256_file(resolved)
    page_count = get_page_count(resolved)

    return ResearchReport(
        id=uuid4().hex,
        file_path=resolved,
        file_hash=file_hash,
        title=None,
        author=None,
        broker=None,
        report_date=None,
        page_count=page_count,
        validation_status="pending",
        validation_errors=[],
        ingested_at=datetime.now(UTC),
    )