"""PDF 合法性校验。"""

from __future__ import annotations

from reproagent.models.report import ResearchReport
from reproagent.utils.pdf import has_pdf_header, is_readable

MAX_PAGES_WARN_THRESHOLD = 200


def validate_pdf(report: ResearchReport) -> ResearchReport:
    """PDF 合法性校验：格式 / 页数 / 可读性。

    失败 → validation_status="invalid" + validation_errors。
    成功 → validation_status="valid"（页数 > 200 仅告警不阻断）。
    """
    errors: list[str] = []
    path = report.file_path

    if path.suffix.lower() != ".pdf":
        errors.append(f"文件扩展名非 .pdf: {path.suffix}")
    elif not has_pdf_header(path):
        errors.append("文件头缺少 %PDF 标记，非合法 PDF")

    if not is_readable(path):
        errors.append("PDF 无法被 pypdf 解析（损坏或加密）")

    if report.page_count == 0:
        errors.append("页数为 0，无法解析")

    if report.page_count > MAX_PAGES_WARN_THRESHOLD:
        errors.append(f"页数异常: 超过 {MAX_PAGES_WARN_THRESHOLD} 页（告警不阻断）")

    if errors and not _only_warning(errors):
        return report.model_copy(
            update={"validation_status": "invalid", "validation_errors": errors}
        )

    return report.model_copy(update={"validation_status": "valid", "validation_errors": errors})


def _only_warning(errors: list[str]) -> bool:
    """仅含页数告警（非阻断）时视为 valid。"""
    return all("告警不阻断" in e for e in errors)
