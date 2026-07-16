from pathlib import Path

from finreportparser.extract.pdf_text import open_pdf
from finreportparser.types import TocEntry


def extract_toc(pdf_path: str | Path) -> list[TocEntry]:
    """Extract Table of Contents (bookmarks) from a PDF document."""
    try:
        with open_pdf(pdf_path) as doc:
            toc_list = doc.get_toc()
            if not toc_list:
                return []

            entries = []
            for item in toc_list:
                # doc.get_toc() returns [[level, title, page], ...]
                # level is 1-based, page is 1-based
                if len(item) >= 3:
                    level, title, page = item[0], item[1], item[2]
                    entries.append(TocEntry(
                        level=int(level),
                        title=str(title),
                        page=int(page)
                    ))
            return entries
    except Exception:
        return []
