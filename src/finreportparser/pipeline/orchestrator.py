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
        config.image_max_edge
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

                # Lightweight pre-check: skip full image extraction when the page has
                # no text blocks and no raw image xrefs (blank-page fast-path).
                if not page_result.blocks:
                    raw_imgs = page.get_images(full=True)
                    if not raw_imgs:
                        images = []
                    else:
                        images = extract_page_images(page, page_num, max_edge=config.image_max_edge)
                else:
                    images = extract_page_images(page, page_num, max_edge=config.image_max_edge)

                decision = route_page(page_result, config.mode, images)

                ocr_blocks = None
                table_blocks = None

                # Short-circuit: blank pages skip rendering, OCR, structure, and VLM
                # entirely so render_full_page is never invoked.
                if decision.page_class == PageClass.BLANK:
                    page_result.classification = decision.page_class
                    cache_store.write_page(page_result, key)
                    release_page_resources(images, ocr_blocks, table_blocks)
                    continue

                rendered_page_bytes = None

                def get_rendered_page(_page=page):
                    nonlocal rendered_page_bytes
                    if rendered_page_bytes is None:
                        rendered_page_bytes = render_full_page(_page, max_edge=config.image_max_edge)
                    return rendered_page_bytes

                if decision.run_ocr:
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

                if decision.run_structure:
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

                        from finreportparser.fusion.table_quality import (
                            is_acceptable_table,
                            score_table,
                        )
                        from finreportparser.fusion.table_repair import repair_table_gfm

                        # Skip crop re-extract by default: full-page PPStructureV3
                        # already returns tables; crop doubles RAM/time and OOM risk.
                        # Always run generic table_repair (glued headers, OCR phrases,
                        # column realign) before the quality gate.
                        accepted_tables = []
                        rejected_count = 0
                        for extract in extracts:
                            if not extract.gfm.strip():
                                continue
                            repair = repair_table_gfm(extract.gfm)
                            gfm = repair.gfm
                            if repair.repaired:
                                logger.info(
                                    "Repaired table on page %d: %s (score %.2f→%.2f)",
                                    page_num,
                                    ",".join(repair.actions),
                                    score_table(extract.gfm),
                                    score_table(gfm),
                                )
                            if is_acceptable_table(gfm):
                                accepted_tables.append(
                                    TableExtract(
                                        gfm=gfm, bbox=extract.bbox, html=extract.html
                                    )
                                )
                            else:
                                rejected_count += 1
                                logger.debug(
                                    "Rejected table on page %d score=%.2f",
                                    page_num,
                                    score_table(gfm),
                                )

                        if rejected_count > 0:
                            logger.info(
                                "Rejected %d low-quality tables on page %d",
                                rejected_count,
                                page_num,
                            )

                        if accepted_tables:
                            table_blocks = [
                                PageBlock(
                                    type=BlockType.TABLE,
                                    text=ext.gfm,
                                    bbox=ext.bbox,
                                    metadata={"table_repaired": True},
                                )
                                for ext in accepted_tables
                            ]
                    except ImportError as e:
                        if "not installed" not in str(e):
                            raise
                        logger.warning(
                            f"{config.table_backend} not available, skipping structure extraction"
                        )
                    except Exception as e:
                        logger.warning("Structure extraction failed on page %d: %s", page_num, e)

                if decision.run_vlm:
                    from finreportparser.vlm.chart_understanding import understand_chart

                    try:
                        vlm = _get_vlm()
                        for img in images:
                            if img.bbox:
                                img_bytes = img.image_bytes
                                if img_bytes:
                                    chart_meta = understand_chart(img_bytes, vlm)
                                    if chart_meta:
                                        chart_meta.bbox = img.bbox
                                        page_result.blocks.append(
                                            PageBlock(
                                                type=BlockType.CHART,
                                                bbox=img.bbox,
                                                text=chart_meta.description,
                                                metadata={"chart_meta": chart_meta.model_dump()},
                                            )
                                        )

                                        if vlm and not chart_meta.description.startswith("["):
                                            mermaid_candidates = vlm.diagram_to_mermaid_candidates(
                                                img_bytes
                                            )
                                            for code in mermaid_candidates:
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
