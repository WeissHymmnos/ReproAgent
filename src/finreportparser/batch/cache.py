"""Page-level cache and resume support for batch PDF processing.

Cache key = SHA256(pdf_content_hash + page_num + mode_flags_canonical)

Each processed page is persisted immediately to disk as JSON under
``cache_dir/{key}.json`` so that interrupted runs can resume by
skipping pages that already have a valid cache entry.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from finreportparser.types import PageResult

logger = logging.getLogger(__name__)

_FULL_HASH_THRESHOLD = 64 * 1024 * 1024  # 64 MiB
_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def compute_pdf_content_hash(pdf_path: Path) -> str:
    """Return the SHA-256 hex digest of *pdf_path*.

    For small/medium PDFs (≤ 64 MiB) the entire file is read and hashed.
    For larger files the content is streamed in 1 MiB chunks to avoid
    excessive memory use.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    sha = hashlib.sha256()
    size = pdf_path.stat().st_size

    if size <= _FULL_HASH_THRESHOLD:
        sha.update(pdf_path.read_bytes())
    else:
        with pdf_path.open("rb") as fh:
            while True:
                chunk = fh.read(_CHUNK_SIZE)
                if not chunk:
                    break
                sha.update(chunk)
    return sha.hexdigest()


def canonical_mode_flags(
    mode: str,
    table_backend: str,
    vlm_backend: str,
    image_max_edge: int,
    **extra: Any,
) -> str:
    """Build a stable, deterministic string from processing options.

    The string is used as part of the cache key so that changing any
    processing parameter invalidates the cache for affected pages.
    """
    parts: list[str] = [
        f"mode={mode}",
        f"table_backend={table_backend}",
        f"vlm_backend={vlm_backend}",
        f"image_max_edge={image_max_edge}",
    ]
    for k in sorted(extra):
        parts.append(f"{k}={extra[k]}")
    return "|".join(parts)


def page_cache_key(pdf_hash: str, page_num: int, mode_flags: str) -> str:
    """Compute the deterministic cache key for a single page."""
    raw = f"{pdf_hash}:{page_num}:{mode_flags}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PageCacheStore:
    """Disk-backed store for per-page :class:`PageResult` artifacts.

    Files are written as ``{cache_dir}/{key}.json`` immediately after
    each page is processed.  Resume is as simple as checking
    :meth:`is_cached` before processing and calling
    :meth:`load_all_page_results` at the end.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _iter_cache_files(self):
        """Yield every ``*.json`` file in *cache_dir*."""
        yield from sorted(self.cache_dir.glob("*.json"))

    def is_cached(self, key_or_page_num: str | int) -> bool:
        """Return *True* if a cache entry exists for *key_or_page_num*.

        Accepts either a cache key (``str``) or a page number (``int``).
        For page numbers the cache directory is scanned for a file whose
        deserialised ``page_num`` matches.
        """
        if isinstance(key_or_page_num, int):
            return self._find_key_for_page(key_or_page_num) is not None
        return self._path_for_key(key_or_page_num).is_file()

    def _find_key_for_page(self, page_num: int) -> str | None:
        """Return the cache key whose stored ``page_num`` == *page_num*."""
        for f in self._iter_cache_files():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("page_num") == page_num:
                    return f.stem
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt cache file skipped: %s", f)
                continue
        return None

    def write_page(self, page_result: PageResult, key: str) -> Path:
        """Persist *page_result* to disk immediately and return the path."""
        path = self._path_for_key(key)
        path.write_text(page_result.model_dump_json(indent=2), encoding="utf-8")
        logger.debug("Cached page %d -> %s", page_result.page_num, path)
        return path

    def read_page(self, key_or_page_num: str | int) -> PageResult | None:
        """Read and return a :class:`PageResult` from cache.

        Returns ``None`` if no cache entry exists.
        """
        if isinstance(key_or_page_num, int):
            key = self._find_key_for_page(key_or_page_num)
            if key is None:
                return None
        else:
            key = key_or_page_num

        path = self._path_for_key(key)
        if not path.is_file():
            return None
        try:
            return PageResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt cache file skipped: %s", path)
            return None

    def list_cached_pages(self) -> list[int]:
        """Return a sorted list of page numbers present in the cache."""
        pages: list[int] = []
        for f in self._iter_cache_files():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                pn = data.get("page_num")
                if isinstance(pn, int):
                    pages.append(pn)
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(pages)

    def load_all_page_results(self) -> list[PageResult]:
        """Load and return every cached :class:`PageResult`, sorted by page."""
        results: list[PageResult] = []
        for f in self._iter_cache_files():
            try:
                results.append(
                    PageResult.model_validate_json(f.read_text(encoding="utf-8"))
                )
            except Exception:
                logger.warning("Corrupt cache file skipped: %s", f)
                continue
        results.sort(key=lambda r: r.page_num)
        return results

    def clear(self) -> None:
        """Remove all cached JSON files."""
        for f in self._iter_cache_files():
            try:
                f.unlink()
            except OSError as e:
                logger.debug("Could not delete cache file %s: %s", f, e)
