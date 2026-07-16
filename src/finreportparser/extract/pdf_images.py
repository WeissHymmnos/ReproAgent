"""Extract images and render region crops from PDF pages using PyMuPDF.

Provides:
    - extract_page_images: list image/figure candidates with bbox from a page
    - render_page_region: render a bbox region of a page as resized PNG/JPEG bytes
    - extract_document_images: convenience wrapper over all pages
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz

from finreportparser.types import BBox, ImageRegion
from finreportparser.utils.image_prep import resize_image_bytes

logger = logging.getLogger(__name__)

PathLike = str | Path


def _rect_to_bbox(rect: fitz.Rect) -> BBox:
    return BBox(x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1)


def _pixmap_to_resized_bytes(
    pix: fitz.Pixmap,
    max_edge: int,
    fmt: str = "PNG",
) -> bytes:
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)
    png_bytes = pix.tobytes("png")
    return resize_image_bytes(png_bytes, max_edge=max_edge, format=fmt)


def extract_page_images(
    page: fitz.Page,
    page_num: int,
    max_edge: int = 768,
    dpi: int = 150,
) -> list[ImageRegion]:
    """List images / figure candidates from a single PDF page.

    Uses PyMuPDF's ``get_image_info`` (with ``xrefs=True``) to obtain
    image bounding boxes, falling back to ``get_images`` + ``get_image_rects``
    for older PyMuPDF versions. Each image region's ``image_bytes`` is
    populated with resized PNG bytes (longest edge <= ``max_edge``).

    Args:
        page: PyMuPDF Page object.
        page_num: 0-based page number (for metadata/logging only).
        max_edge: Maximum longest edge for resized image bytes.
        dpi: DPI for rendering fallback when no raw image xref is available.

    Returns:
        List of ImageRegion with bbox and resized image_bytes.
    """
    regions: list[ImageRegion] = []

    # --- Strategy 1: get_image_info (PyMuPDF >= 1.18.x) ---
    image_infos: list[dict] = []
    try:
        image_infos = page.get_image_info(xrefs=True)
    except Exception:
        # Older PyMuPDF may not support xrefs kwarg
        try:
            image_infos = page.get_image_info()
        except Exception:
            image_infos = []

    if image_infos:
        for info in image_infos:
            bbox_dict = info.get("bbox")
            if bbox_dict is None:
                continue
            rect = fitz.Rect(bbox_dict)
            if rect.is_empty or rect.is_infinite:
                continue
            if rect.width < 20 or rect.height < 20:
                continue
            bbox = _rect_to_bbox(rect)

            image_bytes: bytes | None = None
            xref = info.get("xref", 0)
            if xref:
                try:
                    doc = page.parent
                    pix = fitz.Pixmap(doc, xref)
                    image_bytes = _pixmap_to_resized_bytes(pix, max_edge, "PNG")
                except Exception as exc:
                    logger.debug(
                        "page %d: failed to extract xref %s: %s",
                        page_num, xref, exc,
                    )
                    # Fallback: render the bbox region
                    image_bytes = render_page_region(page, bbox, max_edge, dpi)

            regions.append(ImageRegion(bbox=bbox, image_bytes=image_bytes))
        return regions

    # --- Strategy 2: get_images + get_image_rects (fallback) ---
    raw_images = page.get_images(full=True)
    for img in raw_images:
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        if not rects:
            continue
        for rect in rects:
            if rect.is_empty or rect.is_infinite:
                continue
            if rect.width < 20 or rect.height < 20:
                continue
            bbox = _rect_to_bbox(rect)

            image_bytes: bytes | None = None
            try:
                doc = page.parent
                pix = fitz.Pixmap(doc, xref)
                image_bytes = _pixmap_to_resized_bytes(pix, max_edge, "PNG")
            except Exception as exc:
                logger.debug(
                    "page %d: fallback render for xref %s: %s",
                    page_num, xref, exc,
                )
                image_bytes = render_page_region(page, bbox, max_edge, dpi)

            regions.append(ImageRegion(bbox=bbox, image_bytes=image_bytes))

    try:
        drawings = page.get_drawings()
        for d in drawings:
            rect = d.get("rect")
            if not rect or rect.is_empty or rect.is_infinite:
                continue
            if rect.width > 100 and rect.height > 100:
                bbox = _rect_to_bbox(rect)
                overlap = False
                for r in regions:
                    r_rect = fitz.Rect(r.bbox.to_tuple())
                    intersect = rect.intersect(r_rect)
                    if not intersect.is_empty and (intersect.get_area() / rect.get_area() > 0.5 or intersect.get_area() / r_rect.get_area() > 0.5):
                        overlap = True
                        break
                if not overlap:
                    image_bytes = render_page_region(page, bbox, max_edge, dpi)
                    regions.append(ImageRegion(bbox=bbox, image_bytes=image_bytes))
    except Exception as exc:
        logger.debug("page %d: failed to extract drawings: %s", page_num, exc)

    return regions


def render_page_region(
    page: fitz.Page,
    bbox: BBox,
    max_edge: int = 768,
    dpi: int = 150,
) -> bytes:
    """Render a rectangular region of a page as resized PNG bytes.

    Args:
        page: PyMuPDF Page object.
        bbox: Region to clip (in PDF point coordinates).
        max_edge: Maximum longest edge for the output image.
        dpi: Render DPI (controls pixel density before resize).

    Returns:
        PNG image bytes, resized so longest edge <= ``max_edge`` (no upscale).
    """
    clip = fitz.Rect(bbox.to_tuple())
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, clip=clip)
    return _pixmap_to_resized_bytes(pix, max_edge, "PNG")


def render_full_page(
    page: fitz.Page,
    max_edge: int = 768,
    dpi: int = 150,
) -> bytes:
    """Render an entire page as resized PNG bytes (for scanned pages).

    Args:
        page: PyMuPDF Page object.
        max_edge: Maximum longest edge for the output image.
        dpi: Render DPI.

    Returns:
        PNG image bytes, resized so longest edge <= ``max_edge`` (no upscale).
    """
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    return _pixmap_to_resized_bytes(pix, max_edge, "PNG")


def extract_document_images(
    path: PathLike,
    max_edge: int = 768,
    dpi: int = 150,
) -> dict[int, list[ImageRegion]]:
    """Extract images from all pages of a PDF document.

    Args:
        path: Path to the PDF file.
        max_edge: Maximum longest edge for resized image bytes.
        dpi: DPI for rendering fallbacks.

    Returns:
        Dict mapping 0-based page number to list of ImageRegion.
    """
    result: dict[int, list[ImageRegion]] = {}
    doc = fitz.open(str(path))
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            regions = extract_page_images(page, page_num, max_edge, dpi)
            if regions:
                result[page_num] = regions
    finally:
        doc.close()
    return result