"""PDF 工具：页数、可读性检查。"""

from __future__ import annotations

from pathlib import Path


def get_page_count(path: Path) -> int:
    """用 pypdf 返回 PDF 页数。"""
    raise NotImplementedError("utils.pdf.get_page_count")


def is_readable(path: Path) -> bool:
    """检测 PDF 是否可被 pypdf 打开；扫描件有页面/图片亦视为可读。"""
    raise NotImplementedError("utils.pdf.is_readable")


def has_pdf_header(path: Path) -> bool:
    """文件头是否以 %PDF 开头。"""
    raise NotImplementedError("utils.pdf.has_pdf_header")
