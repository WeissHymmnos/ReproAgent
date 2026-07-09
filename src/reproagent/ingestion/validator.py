"""PDF 合法性校验。"""

from __future__ import annotations

from reproagent.models.report import ResearchReport


def validate_pdf(report: ResearchReport) -> ResearchReport:
    """PDF 合法性校验：格式 / 页数 / 可读性。

    失败 → validation_status=\"invalid\" + validation_errors。
    成功 → validation_status=\"valid\"。
    """
    raise NotImplementedError("ingestion.validator.validate_pdf")
