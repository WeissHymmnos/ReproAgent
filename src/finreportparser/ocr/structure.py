"""
PaddleOCR Structure extraction module.
Note: This module assumes a single-worker environment due to high RAM usage (~9GB).
Compatible with PaddleOCR 2.x (PPStructure) and 3.x (PPStructureV3).
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
        if tag == "tr":
            self.current_row_idx += 1
            self.current_col_idx = 0
        elif tag in ("td", "th"):
            self.in_cell = True
            self.cell_data = []
            self.colspan = 1
            self.rowspan = 1
            for attr, value in attrs:
                if attr == "colspan" and value and value.isdigit():
                    self.colspan = int(value)
                elif attr == "rowspan" and value and value.isdigit():
                    self.rowspan = int(value)

            while (self.current_row_idx, self.current_col_idx) in self.grid:
                self.current_col_idx += 1

        elif tag == "br":
            if self.in_cell:
                self.cell_data.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.in_cell = False
            text = "".join(self.cell_data)
            text = re.sub(r"\s+", " ", text).strip()
            text = text.replace("|", "\\|")

            for r in range(self.rowspan):
                for c in range(self.colspan):
                    cell_val = text if r == 0 and c == 0 else ""
                    self.grid[(self.current_row_idx + r, self.current_col_idx + c)] = cell_val
                    self.max_col = max(self.max_col, self.current_col_idx + c + 1)

            self.current_col_idx += self.colspan

    def handle_data(self, data):
        if self.in_cell:
            self.cell_data.append(data)


def _bbox_from_box_data(box_data) -> BBox | None:
    if box_data is None:
        return None
    try:
        arr = np.asarray(box_data)
        if arr.size == 0:
            return None
        # cell_box_list: Nx4
        if arr.ndim == 2 and arr.shape[0] >= 1 and arr.shape[1] >= 4:
            return BBox(
                x0=float(arr[:, 0].min()),
                y0=float(arr[:, 1].min()),
                x1=float(arr[:, 2].max()),
                y1=float(arr[:, 3].max()),
            )
        # single bbox [x0,y0,x1,y1]
        if arr.ndim == 1 and arr.shape[0] >= 4 and np.issubdtype(arr.dtype, np.number):
            return BBox(
                x0=float(arr[0]),
                y0=float(arr[1]),
                x1=float(arr[2]),
                y1=float(arr[3]),
            )
        # quad [[x,y], ...]
        if arr.ndim == 2 and arr.shape[0] >= 4 and arr.shape[1] >= 2:
            return BBox(
                x0=float(arr[:, 0].min()),
                y0=float(arr[:, 1].min()),
                x1=float(arr[:, 0].max()),
                y1=float(arr[:, 1].max()),
            )
    except Exception:
        return None
    return None


class PaddleStructureExtractor(BaseTableExtractor):
    estimated_ram_gb: float = 9.0

    def __init__(self, lang: str = "ch", cpu_threads: int = 4):
        self.lang = lang
        self.cpu_threads = cpu_threads
        self._engine = None
        self._api = "v2"  # "v2" (PPStructure) or "v3" (PPStructureV3)
        self._ensure_engine()

    def _ensure_engine(self):
        if self._engine is not None:
            return

        # Prefer PaddleOCR 3.x PPStructureV3
        try:
            from paddleocr import PPStructureV3

            self._engine = PPStructureV3(
                lang=self.lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_chart_recognition=False,
                use_formula_recognition=False,
                use_seal_recognition=False,
                use_table_recognition=True,
            )
            self._api = "v3"
            return
        except Exception:
            pass

        try:
            from paddleocr import PPStructure

            try:
                from paddleocr import PPStructureV3 as _V3  # type: ignore

                EngineClass = _V3
                self._api = "v3"
            except ImportError:
                EngineClass = PPStructure
                self._api = "v2"
        except ImportError as e:
            raise ImportError(
                "PaddleOCR structure components are not installed. Please install using:\n"
                "uv pip install paddlepaddle==3.2.0 paddleocr[doc-parser]\n"
                "Note: Use CPU version for ThinkPad compatibility."
            ) from e

        if self._api == "v3":
            self._engine = EngineClass(
                lang=self.lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_chart_recognition=False,
                use_formula_recognition=False,
                use_seal_recognition=False,
                use_table_recognition=True,
            )
        else:
            try:
                self._engine = EngineClass(
                    show_log=False,
                    image_orientation=False,
                    use_gpu=False,
                    cpu_threads=self.cpu_threads,
                    lang=self.lang,
                    layout=True,
                )
            except TypeError:
                self._engine = EngineClass(lang=self.lang)

    def extract_tables(self, image: bytes | Path | Image.Image) -> list[TableExtract]:
        self._ensure_engine()

        img_input = image
        if isinstance(image, Path):
            img_input = str(image)
        elif isinstance(image, Image.Image):
            img_input = np.array(image.convert("RGB"))
        elif isinstance(image, bytes):
            img = Image.open(io.BytesIO(image)).convert("RGB")
            img_input = np.array(img)

        if self._api == "v3":
            return self._extract_tables_v3(img_input)
        return self._extract_tables_v2(img_input)

    def _extract_tables_v3(self, img_input) -> list[TableExtract]:
        if hasattr(self._engine, "predict"):
            result = self._engine.predict(img_input)
        else:
            result = self._engine(img_input)

        extracts: list[TableExtract] = []
        pages = result if isinstance(result, list) else [result]
        for page in pages:
            if page is None:
                continue
            # Prefer table_res_list (structured HTML)
            table_list = None
            if hasattr(page, "get"):
                table_list = page.get("table_res_list")
            if table_list is None and hasattr(page, "table_res_list"):
                table_list = page.table_res_list
            if table_list:
                for table in table_list:
                    html = None
                    if hasattr(table, "get"):
                        html = table.get("pred_html") or table.get("html")
                    elif isinstance(table, dict):
                        html = table.get("pred_html") or table.get("html")
                    if not html:
                        continue
                    gfm = self._html_table_to_gfm(html)
                    if not gfm:
                        continue
                    box_data = None
                    if hasattr(table, "get"):
                        box_data = table.get("cell_box_list")
                    elif isinstance(table, dict):
                        box_data = table.get("cell_box_list")
                    bbox = _bbox_from_box_data(box_data)
                    extracts.append(TableExtract(gfm=gfm, bbox=bbox, html=html))
                if extracts:
                    return extracts

            # Fallback: parsing_res_list table blocks with HTML content
            parsing = None
            if hasattr(page, "get"):
                parsing = page.get("parsing_res_list")
            if parsing is None and hasattr(page, "parsing_res_list"):
                parsing = page.parsing_res_list
            if parsing:
                for block in parsing:
                    label = getattr(block, "label", None)
                    if label is None and isinstance(block, dict):
                        label = block.get("label")
                    if not label or "table" not in str(label).lower():
                        continue
                    content = getattr(block, "content", None)
                    if content is None and isinstance(block, dict):
                        content = block.get("content")
                    if not content or "<table" not in str(content).lower():
                        continue
                    html = str(content)
                    gfm = self._html_table_to_gfm(html)
                    if not gfm:
                        continue
                    bbox = None
                    bb = getattr(block, "bbox", None)
                    if bb is None and isinstance(block, dict):
                        bb = block.get("bbox")
                    if bb is not None and len(bb) >= 4:
                        bbox = BBox(x0=float(bb[0]), y0=float(bb[1]), x1=float(bb[2]), y1=float(bb[3]))
                    extracts.append(TableExtract(gfm=gfm, bbox=bbox, html=html))
        return extracts

    def _extract_tables_v2(self, img_input) -> list[TableExtract]:
        result = self._engine(img_input)

        extracts = []
        for region in result:
            if not isinstance(region, dict):
                continue
            if region.get("type") == "table":
                res = region.get("res", {})
                if "html" in res:
                    html = res["html"]
                    gfm = self._html_table_to_gfm(html)
                    if not gfm:
                        continue

                    box_data = (
                        region.get("bbox")
                        or region.get("box")
                        or region.get("points")
                        or region.get("coordinate")
                    )
                    bbox = _bbox_from_box_data(box_data)
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
        if self._engine is not None and hasattr(self._engine, "close"):
            try:
                self._engine.close()
            except Exception:
                pass
        self._engine = None
        gc.collect()
