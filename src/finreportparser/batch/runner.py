import concurrent.futures
import logging
import multiprocessing
from pathlib import Path

from finreportparser.config import Config
from finreportparser.extract.pdf_text import CorruptPdfError, EncryptedPdfError
from finreportparser.pipeline.orchestrator import parse_pdf_to_files
from finreportparser.types import PageClass
from finreportparser.utils.memory import enforce_memory_matrix

logger = logging.getLogger(__name__)

def _process_single_pdf(
    pdf_path: Path, config: Config, out_dir: str | None, resume: bool
) -> tuple[Path, bool, str | None, str | None, str | None]:
    try:
        md_path, json_path = parse_pdf_to_files(
            pdf_path, config, out_dir=out_dir, resume=resume
        )
        return (pdf_path, True, str(md_path), str(json_path), None)
    except (EncryptedPdfError, CorruptPdfError) as e:
        return (pdf_path, False, None, None, f"SKIP: {e}")
    except Exception as e:
        return (pdf_path, False, None, None, f"FAIL: {e}")

def run_batch(dir_path: Path, config: Config, out_dir: str | None = None, resume: bool = True) -> tuple[int, int]:
    pdf_files = sorted(dir_path.glob("*.pdf"))
    if not pdf_files:
        logger.info(f"No PDF files found in {dir_path}")
        return 0, 0

    logger.info(f"Found {len(pdf_files)} PDF(s) in {dir_path}")

    workers = enforce_memory_matrix(
        PageClass.MIXED,
        config.workers,
        table_backend=config.table_backend,
    )

    success = 0
    failed = 0

    if workers <= 1:
        for pdf in pdf_files:
            logger.info(f"--- {pdf.name} ---")
            _, is_success, md_path, json_path, err_msg = _process_single_pdf(pdf, config, out_dir, resume)
            if is_success:
                logger.info(f"  markdown: {md_path}")
                logger.info(f"  json:     {json_path}")
                success += 1
            else:
                logger.info(f"  {err_msg}")
                failed += 1
    else:
        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as executor:
            futures = {
                executor.submit(_process_single_pdf, pdf, config, out_dir, resume): pdf
                for pdf in pdf_files
            }

            for future in concurrent.futures.as_completed(futures):
                pdf = futures[future]
                logger.info(f"--- {pdf.name} ---")
                try:
                    _, is_success, md_path, json_path, err_msg = future.result()
                    if is_success:
                        logger.info(f"  markdown: {md_path}")
                        logger.info(f"  json:     {json_path}")
                        success += 1
                    else:
                        logger.info(f"  {err_msg}")
                        failed += 1
                except Exception as e:
                    logger.error(f"  FAIL: {e}")
                    failed += 1

    return success, failed
