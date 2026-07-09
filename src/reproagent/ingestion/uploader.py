"""PDF 上传 → ResearchReport。"""

from __future__ import annotations

from pathlib import Path

from reproagent.models.report import ResearchReport


def upload_pdf(file_path: Path) -> ResearchReport:
    """上传一篇 PDF → 创建 ResearchReport（file_hash + page_count 即时计算）。

    单篇支持；批量 for 循环调用即可。
    """
    raise NotImplementedError("ingestion.uploader.upload_pdf")
