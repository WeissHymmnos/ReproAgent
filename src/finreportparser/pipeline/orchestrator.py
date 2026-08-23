import logging
from pathlib import Path

from finreportparser.batch.cache import (
    PageCacheStore,
    canonical_mode_flags,
    compute_pdf_content_hash,
    page_cache_key,
)
from finreportparser.config import Config, load_config
from finreportparser.extract.pdf_images import extract_page_images, render_full_page
from finreportparser.extract.pdf_text import CorruptPdfError, extract_page_text, open_pdf
from finreportparser.extract.toc import extract_toc
from finreportparser.fusion.metrics import extract_metrics, extract_metrics_from_table
from finreportparser.fusion.quality import run_quality_checks
from finreportparser.fusion.tables_cross_page import merge_continued_tables
from finreportparser.output import write_document
from finreportparser.pipeline.page_router import route_page
from finreportparser.pipeline.reconstruct import merge_page_content, reconstruct_document_pages
from finreportparser.types import (
    BBox,
    BlockType,
    DocumentMetadata,
    DocumentResult,
    PageBlock,
    PageClass,
    QualityMode,
    TableExtract,
)
from finreportparser.utils.memory import release_page_resources

logger = logging.getLogger(__name__)

def ocr_lines_to_blocks(lines: list) -> list[PageBlock]:
    blocks = []
    for line in lines:
        bbox = None
        if line.bbox:
            xs = [p[0] for p in line.bbox]
            ys = [p[1] for p in line.bbox]
            bbox = BBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
        blocks.append(PageBlock(type=BlockType.TEXT, text=line.text, confidence=line.confidence, bbox=bbox))
    return blocks

def parse_pdf(
    pdf_path: Path | str,
    config: Config | None = None,
    *,
    out_dir: Path | str | None = None,
    resume: bool | None = None,
) -> DocumentResult:
    """Parse a PDF document end-to-end."""
    if config is None:
        config = load_config()

    pdf_path = Path(pdf_path)

    if out_dir is None:
        out_dir = Path(config.out_dir)
    else:
        out_dir = Path(out_dir)

    if resume is None:
        resume = config.resume

    stem = pdf_path.stem

    if config.cache_dir:
        cache_dir = Path(config.cache_dir)
    else:
        cache_dir = out_dir / stem / ".cache"

    cache_store = PageCacheStore(cache_dir)

    try:
        pdf_hash = compute_pdf_content_hash(pdf_path)
    except Exception as e:
        raise CorruptPdfError(f"Failed to hash PDF: {e}") from e

    mode_flags = canonical_mode_flags(
        config.mode,
        config.table_backend,
        config.vlm_backend,
        config.image_max_edge,
        prefer_text_tables=getattr(config, "prefer_text_tables", True),
        allow_structure=getattr(config, "allow_structure", True),
        allow_ocr=getattr(config, "allow_ocr", True),
        allow_vlm=getattr(config, "allow_vlm", False),
    )

    # Reuse heavy Paddle engines across pages to avoid reload/OOM (SIGBUS).
    shared_ocr_engine = None
    shared_structure_extractor = None
    shared_vlm = None

    def _get_ocr_engine():
        nonlocal shared_ocr_engine
        if shared_ocr_engine is None:
            if getattr(config, "ocr_backend", "paddle") == "unlimited-ocr":
                from finreportparser.ocr.unlimited_ocr import UnlimitedOcrEngine

                shared_ocr_engine = UnlimitedOcrEngine()
            else:
                from finreportparser.ocr.paddle_ocr import PaddleOcrEngine

                shared_ocr_engine = PaddleOcrEngine(enable_hpi=config.enable_hpi)
        return shared_ocr_engine

    def _get_structure_extractor():
        nonlocal shared_structure_extractor
        if shared_structure_extractor is None:
            if config.table_backend == "unlimited-ocr":
                from finreportparser.ocr.unlimited_ocr import UnlimitedOcrTableExtractor

                shared_structure_extractor = UnlimitedOcrTableExtractor()
            elif config.table_backend == "mineru":
                from finreportparser.ocr.mineru_backend import MinerUTableExtractor

                shared_structure_extractor = MinerUTableExtractor()
            else:
                from finreportparser.ocr.structure import PaddleStructureExtractor

                shared_structure_extractor = PaddleStructureExtractor()
        return shared_structure_extractor

    def _get_vlm():
        nonlocal shared_vlm
        if shared_vlm is None and config.vlm_backend != "none":
            from finreportparser.vlm.registry import get_vlm

            shared_vlm = get_vlm(config.vlm_backend)
        return shared_vlm

    try:
        with open_pdf(pdf_path) as doc:
            for i, page in enumerate(doc):
                page_num = i + 1
                key = page_cache_key(pdf_hash, page_num, mode_flags)

                if resume and cache_store.is_cached(key):
                    logger.debug(f"Skipping cached page {page_num}")
                    continue

                logger.info("Parsing page %d/%d", page_num, len(doc))
                page_result = extract_page_text(page, page_num)

                # Fast path: route with text only first; skip image decode on
                # pure-text / table pages (big speed win for long research PDFs).
                pre = route_page(page_result, config.mode, images=None)
                text_join = "\n".join(
                    b.text or "" for b in page_result.blocks if b.text
                )
                chart_kw = (
                    "图表" in text_join
                    or "Figure" in text_join
                    or "figure" in text_join.lower()
                )
                need_images = (
                    page_result.needs_ocr
                    or pre.page_class
                    in (
                        PageClass.SCANNED,
                        PageClass.CHART_CANDIDATE,
                        PageClass.MIXED,
                        PageClass.BLANK,
                    )
                    or chart_kw
                    or pre.run_vlm
                )
                if need_images:
                    if not page_result.blocks:
                        raw_imgs = page.get_images(full=True)
                        images = (
                            []
                            if not raw_imgs
                            else extract_page_images(
                                page, page_num, max_edge=config.image_max_edge
                            )
                        )
                    else:
                        images = extract_page_images(
                            page, page_num, max_edge=config.image_max_edge
                        )
                    decision = route_page(page_result, config.mode, images)
                else:
                    images = []
                    decision = pre

                ocr_blocks = None
                table_blocks = None

                # Short-circuit: blank pages skip rendering, OCR, structure, and VLM
                # entirely so render_full_page is never invoked.
                if decision.page_class == PageClass.BLANK:
                    page_result.classification = decision.page_class
                    cache_store.write_page(page_result, key)
                    release_page_resources(images, ocr_blocks, table_blocks)
                    continue

                from finreportparser.fusion.table_quality import (
                    is_acceptable_table,
                    score_table,
                )
                from finreportparser.fusion.table_repair import repair_table_gfm

                def _accept_tables(
                    extracts: list, *, source: str
                ) -> list[PageBlock]:
                    accepted: list[PageBlock] = []
                    for extract in extracts:
                        gfm_raw = extract if isinstance(extract, str) else extract.gfm
                        if not gfm_raw or not str(gfm_raw).strip():
                            continue
                        if isinstance(extract, str):
                            bbox = None
                        else:
                            bbox = extract.bbox
                        repair = repair_table_gfm(str(gfm_raw))
                        gfm = repair.gfm
                        if is_acceptable_table(gfm):
                            accepted.append(
                                PageBlock(
                                    type=BlockType.TABLE,
                                    text=gfm,
                                    bbox=bbox,
                                    metadata={
                                        "table_source": source,
                                        "table_repaired": repair.repaired,
                                        "table_score": score_table(gfm),
                                    },
                                )
                            )
                    return accepted

                # --- Zero-load path: text-layer tables (digital PDFs) ---
                text_table_ok = False
                if getattr(config, "prefer_text_tables", True) and not page_result.needs_ocr:
                    try:
                        from finreportparser.extract.text_tables import (
                            extract_tables_from_page,
                        )

                        text_extracts = extract_tables_from_page(page)
                        if text_extracts:
                            table_blocks = _accept_tables(text_extracts, source="text_layer")
                            if table_blocks:
                                scores = [
                                    (b.metadata or {}).get("table_score", 0.0)
                                    for b in table_blocks
                                ]
                                min_score = float(
                                    getattr(config, "text_table_min_score", 0.45)
                                )
                                text_table_ok = max(scores) >= min_score
                                logger.debug(
                                    "Page %d text-layer tables=%d max_score=%.2f ok=%s",
                                    page_num,
                                    len(table_blocks),
                                    max(scores),
                                    text_table_ok,
                                )
                    except Exception as e:
                        logger.debug("Text-layer tables failed page %d: %s", page_num, e)

                rendered_page_bytes = None

                def get_rendered_page(_page=page):
                    nonlocal rendered_page_bytes
                    if rendered_page_bytes is None:
                        rendered_page_bytes = render_full_page(
                            _page, max_edge=config.image_max_edge
                        )
                    return rendered_page_bytes

                run_ocr = (
                    decision.run_ocr
                    and getattr(config, "allow_ocr", True)
                )
                if run_ocr:
                    try:
                        engine = _get_ocr_engine()
                        img_bytes = get_rendered_page()
                        lines = engine.predict(img_bytes)
                        ocr_blocks = ocr_lines_to_blocks(lines)
                    except ImportError as e:
                        if "not installed" not in str(e):
                            raise
                        logger.warning("OCR Engine not available, skipping OCR")
                    except Exception as e:
                        logger.warning("OCR failed on page %d: %s", page_num, e)

                # Structure only when allowed AND (text tables weak OR forced quality)
                need_structure = (
                    decision.run_structure
                    and getattr(config, "allow_structure", True)
                )
                if need_structure and getattr(config, "structure_only_if_text_weak", True):
                    if text_table_ok:
                        need_structure = False
                        logger.debug(
                            "Page %d skip structure (text tables sufficient)", page_num
                        )

                if need_structure:
                    try:
                        extractor = _get_structure_extractor()
                        img_bytes = get_rendered_page()

                        if hasattr(extractor, "extract_tables"):
                            raw_extracts = extractor.extract_tables(img_bytes)
                        else:
                            gfm = extractor.extract_table(img_bytes)
                            raw_extracts = [gfm] if gfm.strip() else []

                        extracts = []
                        for item in raw_extracts:
                            if isinstance(item, str):
                                extracts.append(TableExtract(gfm=item))
                            else:
                                extracts.append(item)

                        struct_blocks = _accept_tables(extracts, source="structure")
                        # Prefer structure tables if they score better / fill gaps
                        if struct_blocks:
                            if not table_blocks:
                                table_blocks = struct_blocks
                            else:
                                # Keep both if non-overlapping; else take higher-scoring set
                                t_score = max(
                                    (b.metadata or {}).get("table_score", 0) for b in table_blocks
                                )
                                s_score = max(
                                    (b.metadata or {}).get("table_score", 0) for b in struct_blocks
                                )
                                if s_score >= t_score:
                                    table_blocks = struct_blocks
                    except ImportError as e:
                        if "not installed" not in str(e):
                            raise
                        logger.warning(
                            f"{config.table_backend} not available, skipping structure extraction"
                        )
                    except Exception as e:
                        logger.warning(
                            "Structure extraction failed on page %d: %s", page_num, e
                        )

                run_vlm = (
                    decision.run_vlm
                    and getattr(config, "allow_vlm", False)
                    and config.vlm_backend != "none"
                )
                if run_vlm:
                    from finreportparser.vlm.chart_understanding import understand_chart

                    try:
                        vlm = _get_vlm()
                        # Speed: skip tiny logos; process largest images first; cap count
                        max_charts = int(getattr(config, "max_vlm_images", 4) or 4)
                        min_area = 80 * 80
                        candidates = []
                        for img in images:
                            if not img.bbox or not img.image_bytes:
                                continue
                            area = max(
                                0.0,
                                (img.bbox.x1 - img.bbox.x0) * (img.bbox.y1 - img.bbox.y0),
                            )
                            if area < min_area:
                                continue
                            candidates.append((area, img))
                        candidates.sort(key=lambda x: -x[0])
                        candidates = candidates[:max_charts]

                        for _area, img in candidates:
                            img_bytes = img.image_bytes
                            chart_meta = understand_chart(img_bytes, vlm)
                            if not chart_meta:
                                continue
                            chart_meta.bbox = img.bbox
                            page_result.blocks.append(
                                PageBlock(
                                    type=BlockType.CHART,
                                    bbox=img.bbox,
                                    text=chart_meta.description,
                                    metadata={"chart_meta": chart_meta.model_dump()},
                                )
                            )

                            # Mermaid only for framework/flowchart; pass type to skip re-classify
                            ctype = (chart_meta.chart_type or "").lower()
                            if ctype in ("framework", "flowchart") and vlm is not None:
                                if hasattr(vlm, "diagram_to_mermaid_candidates"):
                                    try:
                                        mermaid_candidates = vlm.diagram_to_mermaid_candidates(
                                            img_bytes, chart_type=ctype
                                        )
                                    except TypeError:
                                        mermaid_candidates = vlm.diagram_to_mermaid_candidates(
                                            img_bytes
                                        )
                                else:
                                    mermaid_candidates = []
                                for code in mermaid_candidates or []:
                                    from finreportparser.fusion.mermaid import (
                                        mermaid_or_fallback,
                                    )

                                    valid_code, fallback = mermaid_or_fallback(
                                        code,
                                        "Failed to generate valid Mermaid diagram.",
                                    )
                                    if valid_code:
                                        page_result.blocks.append(
                                            PageBlock(
                                                type=BlockType.MERMAID,
                                                bbox=img.bbox,
                                                text=valid_code,
                                                metadata={"mermaid": valid_code},
                                            )
                                        )
                    except Exception as e:
                        logger.warning("VLM failed on page %d: %s", page_num, e)

                merged_blocks = merge_page_content(
                    page_result.blocks,
                    ocr_blocks,
                    table_blocks,
                    None,  # image_placeholders
                    page_result.needs_ocr,
                )

                page_result.blocks = merged_blocks
                page_result.classification = decision.page_class

                cache_store.write_page(page_result, key)

                release_page_resources(images, ocr_blocks, table_blocks)
    finally:
        for eng in (shared_ocr_engine, shared_structure_extractor, shared_vlm):
            if eng is not None and hasattr(eng, "unload"):
                try:
                    eng.unload()
                except Exception:
                    pass

    pages = cache_store.load_all_page_results()

    # Drop headers/footers (geometry + patterns + cross-page repeats)
    if getattr(config, "strip_headers_footers", True):
        from finreportparser.fusion.headers_footers import filter_document_headers_footers

        pages = filter_document_headers_footers(pages)

    # Second-pass table repair on cached/merged pages (covers resume + older caches)
    from finreportparser.fusion.table_repair import repair_table_gfm

    for page in pages:
        for block in page.blocks:
            if block.type == BlockType.TABLE and block.text:
                repaired = repair_table_gfm(block.text)
                if repaired.repaired:
                    block.text = repaired.gfm
                    meta = dict(block.metadata or {})
                    meta["table_repair_actions"] = repaired.actions
                    block.metadata = meta

    recognizer = None
    if config.formula_backend in ("pix2text", "auto"):
        from finreportparser.ocr.formula_backend import get_formula_backend
        recognizer = get_formula_backend("pix2text")

    def crop_callback(page_num: int, bbox: BBox) -> bytes:
        with open_pdf(pdf_path) as doc:
            page = doc[page_num - 1]
            from finreportparser.extract.pdf_images import render_page_region
            return render_page_region(page, bbox, max_edge=config.image_max_edge)

    pages = reconstruct_document_pages(
        pages, formula_backend=config.formula_backend, recognizer=recognizer, crop_callback=crop_callback
    )
    pages = merge_continued_tables(pages)

    metadata = DocumentMetadata(
        source=str(pdf_path),
        mode=QualityMode(config.mode),
        title=stem
    )

    toc_entries = extract_toc(pdf_path)
    doc = DocumentResult(metadata=metadata, pages=pages, toc=toc_entries)

    metrics = []
    for page in pages:
        page_text = "\n\n".join(block.text for block in page.blocks if block.text)
        metrics.extend(extract_metrics(page_text, page_num=page.page_num))

        for block in page.blocks:
            if block.type == BlockType.TABLE and block.text:
                metrics.extend(extract_metrics_from_table(block.text, page_num=page.page_num))
    doc.metrics = metrics

    run_quality_checks(doc)

    return doc

def parse_pdf_to_files(
    pdf_path: Path | str,
    config: Config | None = None,
    *,
    out_dir: Path | str | None = None,
    resume: bool | None = None,
) -> tuple[Path, Path]:
    """Parse a PDF document and write the results to markdown and JSON files."""
    if config is None:
        config = load_config()

    if out_dir is None:
        out_dir = Path(config.out_dir)
    else:
        out_dir = Path(out_dir)

    doc = parse_pdf(pdf_path, config, out_dir=out_dir, resume=resume)

    return write_document(
        doc,
        out_dir=out_dir,
        stem=Path(pdf_path).stem,
        sidecar=config.sidecar,
        pdf_path=Path(pdf_path),
    )
