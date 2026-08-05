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


def pdf_pages_to_base64(path: Path, max_pages: int = 10) -> list[str]:
    """将 PDF 页转换为 base64 编码的 PNG 字符串，供 Vision LLM 使用。

    为了性能和上下文长度控制，默认最多只转换前 max_pages 页。
    """
    import base64

    import fitz  # PyMuPDF

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    encoded_pages = []
    try:
        doc = fitz.open(str(path))
        # 限制转换的页数
        page_count = min(len(doc), max_pages)
        for i in range(page_count):
            page = doc[i]
            # 缩放系数，提高清晰度
            zoom = 2.0
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")
            encoded = base64.b64encode(png_bytes).decode("utf-8")
            encoded_pages.append(encoded)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(f"Failed to convert PDF to base64 images: {e}")
    finally:
        if "doc" in locals():
            doc.close()

    return encoded_pages
