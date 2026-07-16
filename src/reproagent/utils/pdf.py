"""PDF 工具：页数、可读性检查。"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from reproagent.exceptions import ValidationError


def get_page_count(path: Path) -> int:
    """用 pypdf 返回 PDF 页数。"""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValidationError(f"Path is not a file: {path}")
    try:
        reader = PdfReader(path)
        return len(reader.pages)
    except Exception as e:
        raise ValidationError(f"Failed to read PDF page count from {path}: {e}") from e


def is_readable(path: Path) -> bool:
    """检测 PDF 是否可被 pypdf 打开；扫描件有页面/图片亦视为可读。"""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValidationError(f"Path is not a file: {path}")
    try:
        reader = PdfReader(path)
        return len(reader.pages) >= 0
    except Exception:
        return False


def has_pdf_header(path: Path) -> bool:
    """文件头是否以 %PDF 开头。"""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValidationError(f"Path is not a file: {path}")
    with open(path, "rb") as f:
        header = f.read(4)
    return header.startswith(b"%PDF")
