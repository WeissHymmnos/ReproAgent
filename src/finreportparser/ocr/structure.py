"""
PaddleOCR Structure extraction module.
Note: This module assumes a single-worker environment due to high RAM usage (~9GB).
"""
import gc
import io
import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from PIL import Image

from finreportparser.ocr.base import BaseTableExtractor
from finreportparser.types import BBox, TableExtract


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.grid = {}
        self.current_row_idx = -1
        self.current_col_idx = 0
        self.in_cell = False
        self.cell_data = []
        self.colspan = 1
        self.rowspan = 1
        self.max_col = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.current_row_idx += 1
            self.current_col_idx = 0
        elif tag in ('td', 'th'):
            self.in_cell = True
            self.cell_data = []
            self.colspan = 1
            self.rowspan = 1
            for attr, value in attrs:
                if attr == 'colspan' and value and value.isdigit():
                    self.colspan = int(value)
                elif attr == 'rowspan' and value and value.isdigit():
                    self.rowspan = int(value)

            while (self.current_row_idx, self.current_col_idx) in self.grid:
                self.current_col_idx += 1

        elif tag == 'br':
            if self.in_cell:
                self.cell_data.append(' ')

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.in_cell = False
            text = ''.join(self.cell_data)
            text = re.sub(r'\s+', ' ', text).strip()
            text = text.replace('|', '\\|')

            for r in range(self.rowspan):
                for c in range(self.colspan):
                    cell_val = text if r == 0 and c == 0 else ""
                    self.grid[(self.current_row_idx + r, self.current_col_idx + c)] = cell_val
                    self.max_col = max(self.max_col, self.current_col_idx + c + 1)

            self.current_col_idx += self.colspan

    def handle_data(self, data):
        if self.in_cell:
            self.cell_data.append(data)

class PaddleStructureExtractor(BaseTableExtractor):
    estimated_ram_gb: float = 9.0

    def __init__(self, lang: str = "ch", cpu_threads: int = 4):
        self.lang = lang
        self.cpu_threads = cpu_threads
        self._engine = None
        self._ensure_engine()

    def _ensure_engine(self):
        if self._engine is not None:
            return

        try:
            from paddleocr import PPStructure
            try:
                from paddleocr import PPStructureV3
                EngineClass = PPStructureV3
            except ImportError:
                EngineClass = PPStructure
        except ImportError as e:
            raise ImportError(
                "PaddleOCR structure components are not installed. Please install using:\n"
                "uv pip install paddlepaddle==3.2.0 paddleocr[doc-parser]\n"
                "Note: Use CPU version for ThinkPad compatibility."
            ) from e

        self._engine = EngineClass(
            show_log=False,
            image_orientation=False,
            use_gpu=False,
            cpu_threads=self.cpu_threads,
            lang=self.lang,
            layout=True,
        )

    def extract_tables(self, image: bytes | Path | Image.Image) -> list[TableExtract]:
        self._ensure_engine()

        img_input = image
        if isinstance(image, Path):
            img_input = str(image)
        elif isinstance(image, Image.Image):
            img_input = np.array(image.convert('RGB'))
        elif isinstance(image, bytes):
            img = Image.open(io.BytesIO(image)).convert('RGB')
            img_input = np.array(img)

        result = self._engine(img_input)

        extracts = []
        for region in result:
            if region.get('type') == 'table':
                res = region.get('res', {})
                if 'html' in res:
                    html = res['html']
                    gfm = self._html_table_to_gfm(html)
                    if not gfm:
                        continue

                    bbox = None
                    box_data = (
                        region.get('bbox') or
                        region.get('box') or
                        region.get('points') or
                        region.get('coordinate')
                    )
                    if box_data:
                        try:
                            if len(box_data) == 4 and isinstance(box_data[0], (int, float)):
                                bbox = BBox(x0=box_data[0], y0=box_data[1], x1=box_data[2], y1=box_data[3])
                            elif len(box_data) == 4 and isinstance(box_data[0], (list, tuple)):
                                xs = [p[0] for p in box_data]
                                ys = [p[1] for p in box_data]
                                bbox = BBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
                        except Exception:
                            pass

                    extracts.append(TableExtract(gfm=gfm, bbox=bbox, html=html))

        return extracts

    def extract_table(self, image: bytes | Path | Image.Image) -> str:
        tables = self.extract_tables(image)
        return tables[0].gfm if tables else ""

    def _html_table_to_gfm(self, html: str) -> str:
        parser = _TableParser()
        parser.feed(html)

        if not parser.grid:
            return ""

        max_row = max(r for r, c in parser.grid.keys())
        max_col = parser.max_col

        if max_col == 0:
            return ""

        markdown_lines = []
        for r in range(max_row + 1):
            row_cells = []
            for c in range(max_col):
                row_cells.append(parser.grid.get((r, c), ""))

            line = "| " + " | ".join(row_cells) + " |"
            markdown_lines.append(line)

            if r == 0:
                separator = "| " + " | ".join(["---"] * max_col) + " |"
                markdown_lines.append(separator)

        return "\n".join(markdown_lines)

    def unload(self) -> None:
        self._engine = None
        gc.collect()
