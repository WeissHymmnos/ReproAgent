import re
from dataclasses import dataclass

from finreportparser.types import BlockType, ImageRegion, PageClass, PageResult, QualityMode


@dataclass
class RouteDecision:
    run_ocr: bool
    run_structure: bool
    run_vlm: bool
    page_class: PageClass

def classify_page(page: PageResult, images: list[ImageRegion] | None = None) -> PageClass:
    if images is None:
        images = []

    text_blocks = [b for b in page.blocks if b.type == BlockType.TEXT and b.text]
    full_text = "\n".join(b.text for b in text_blocks).strip()

    has_text = len(full_text) > 0
    has_images = len(images) > 0

    if not has_text and not has_images:
        return PageClass.BLANK

    if (page.needs_ocr and has_images) or (not has_text and has_images):
        return PageClass.SCANNED

    lines = full_text.split('\n')
    pipe_count = full_text.count('|')
    digit_heavy_lines = sum(1 for line in lines if sum(c.isdigit() for c in line) > len(line) * 0.3 and len(line) > 5)

    if pipe_count > 5 or digit_heavy_lines > 3:
        return PageClass.TABLE_CANDIDATE

    has_precise_chart_keyword = (
        "图表" in full_text.lower() or
        "figure" in full_text.lower() or
        "chart" in full_text.lower() or
        bool(re.search(r'图\s*[0-9一二三四五六七八九十]+', full_text))
    )

    if has_images and (len(full_text) < 200 or has_precise_chart_keyword):
        return PageClass.CHART_CANDIDATE

    if len(full_text) > 200 and not page.needs_ocr and not has_images:
        return PageClass.TEXT_RICH

    return PageClass.MIXED

def route_page(
    page: PageResult,
    mode: QualityMode | str,
    images: list[ImageRegion] | None = None,
) -> RouteDecision:
    if isinstance(mode, str):
        mode = QualityMode(mode)

    page_class = classify_page(page, images)

    run_ocr = False
    run_structure = False
    run_vlm = False

    if mode == QualityMode.FAST:
        if page.needs_ocr or page_class == PageClass.SCANNED:
            run_ocr = True
    elif mode == QualityMode.BALANCED:
        if page.needs_ocr or page_class == PageClass.SCANNED:
            run_ocr = True
        if page_class == PageClass.TABLE_CANDIDATE:
            run_structure = True
            if images and len(images) >= 1:
                run_vlm = True
        if page_class == PageClass.CHART_CANDIDATE:
            run_vlm = True
        if page_class == PageClass.MIXED and images and len(images) >= 1:
            run_vlm = True
    elif mode == QualityMode.MAX_QUALITY:
        if page.needs_ocr or page_class in (
            PageClass.SCANNED,
            PageClass.MIXED,
            PageClass.CHART_CANDIDATE,
            PageClass.TABLE_CANDIDATE,
        ):
            run_ocr = True
        if page_class in (PageClass.TABLE_CANDIDATE, PageClass.MIXED):
            run_structure = True
        if page_class in (PageClass.CHART_CANDIDATE, PageClass.MIXED):
            run_vlm = True

    return RouteDecision(
        run_ocr=run_ocr,
        run_structure=run_structure,
        run_vlm=run_vlm,
        page_class=page_class
    )
