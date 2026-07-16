from contextlib import contextmanager
from pathlib import Path

import fitz

from finreportparser.types import BBox, BlockType, PageBlock, PageResult
from finreportparser.utils.text_quality import cjk_ratio, is_garbled_chinese


class EncryptedPdfError(Exception):
    """Raised when a PDF is encrypted and cannot be read."""
    pass

class CorruptPdfError(Exception):
    """Raised when a PDF is corrupt or unreadable."""
    pass

@contextmanager
def open_pdf(path: str | Path) -> fitz.Document:
    """Open a PDF document safely, ensuring it is closed after use."""
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise CorruptPdfError(f"Failed to open PDF: {e}") from e

    try:
        if doc.is_encrypted:
            raise EncryptedPdfError(f"PDF is encrypted: {path}")
        yield doc
    finally:
        doc.close()

def extract_page_text(page: fitz.Page, page_num_1based: int) -> PageResult:
    """Extract text blocks from a single PDF page."""
    page_dict = page.get_text("dict")
    blocks = []

    for block in page_dict.get("blocks", []):
        if block.get("type") == 0:
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            text_lines = []
            font_sizes = []
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_lines.append(span.get("text", ""))
                    font_sizes.append(span.get("size", 0))

            text = "".join(text_lines).strip()
            if not text:
                continue

            avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 0

            blocks.append(PageBlock(
                type=BlockType.TEXT,
                bbox=BBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
                text=text,
                metadata={"font_size": avg_font_size}
            ))

    blocks.sort(key=lambda b: (round(b.bbox.y0 / 10) * 10 if b.bbox else 0, b.bbox.x0 if b.bbox else 0))

    full_text = "\n".join(b.text for b in blocks if b.text)
    needs_ocr = False

    if full_text:
        non_ws_len = len([c for c in full_text if not c.isspace()])
        if non_ws_len > 20:
            if is_garbled_chinese(full_text) or cjk_ratio(full_text) < 0.30:
                needs_ocr = True

    return PageResult(
        page_num=page_num_1based,
        blocks=blocks,
        needs_ocr=needs_ocr,
        width=page.rect.width,
        height=page.rect.height
    )

def extract_document_text(path: str | Path) -> list[PageResult]:
    """Extract text from all pages of a PDF document."""
    results = []
    with open_pdf(path) as doc:
        for i, page in enumerate(doc):
            results.append(extract_page_text(page, i + 1))
    return results
