import importlib.util
import logging
import re
from typing import Any

from finreportparser.types import ChartMeta
from finreportparser.vlm.base import BaseVLMProvider

logger = logging.getLogger(__name__)

HAS_PADDLE = importlib.util.find_spec("paddleocr") is not None

_BAR_KEYWORDS = ("柱", "bar", "条形", "histogram")
_LINE_KEYWORDS = ("折线", "line", "趋势", "走势", "曲线", "净值")
_PIE_KEYWORDS = ("饼", "pie", "占比", "结构", "donut")
_FLOW_KEYWORDS = ("流程", "步骤", "→", "->", "flowchart", "flow")
_NOISE_KEYWORDS = {"haitong", "海通证券", "证券研究报告", "金融工程研究", "请务必阅读", "资料来源", "数据来源"}


def _is_noise(text: str) -> bool:
    text_lower = text.lower().strip()
    if any(kw in text_lower for kw in _NOISE_KEYWORDS):
        return True
    if len(text_lower) < 2:
        if not re.match(r'^[\d%]+$', text_lower):
            return True
    return False


def _extract_title(texts: list[str]) -> str:
    for text in texts:
        if re.search(r'^(图|图表|Figure)\s*\d+', text, re.IGNORECASE):
            return text.strip()[:120]
    return texts[0].strip()[:120] if texts else "Chart"


def _heuristic_chart_type(texts: list[str]) -> str:
    joined = " ".join(texts).lower()
    if any(kw in joined for kw in _PIE_KEYWORDS):
        return "pie"
    if any(kw in joined for kw in _BAR_KEYWORDS):
        return "bar"
    if any(kw in joined for kw in _LINE_KEYWORDS):
        return "line"
    
    date_count = sum(1 for t in texts if re.match(r'^(20\d{2}|\d{2}-\d{2}|\d{4}-\d{2})$', t.strip()))
    if date_count >= 3:
        return "line"
        
    return "unknown"


def _has_flow_keywords(texts: list[str]) -> bool:
    joined = " ".join(texts).lower()
    return any(kw in joined for kw in _FLOW_KEYWORDS)


def _build_structured_description(lines: list[Any], chart_type: str, title: str) -> str:
    valid_lines = [
        ln
        for ln in lines
        if getattr(ln, "bbox", None)
        and len(ln.bbox) == 4
        and ln.text
        and ln.text.strip()
        and not _is_noise(ln.text)
    ]
    if not valid_lines:
        return "图中主要为图形元素，OCR 未识别到可读坐标/标注"

    if len(valid_lines) <= 2:
        chart_type_zh = {
            "bar": "柱状图",
            "line": "折线图",
            "pie": "饼图",
            "unknown": "图表"
        }.get(chart_type, "图表")
        labels = "，".join(ln.text.strip() for ln in valid_lines)
        return f"{chart_type_zh}，包含标签：{labels}"

    items = []
    min_x = float('inf')
    max_x = float('-inf')
    min_y = float('inf')
    max_y = float('-inf')

    for ln in valid_lines:
        text = ln.text.strip()
        bbox = ln.bbox
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        cx = sum(xs) / 4.0
        cy = sum(ys) / 4.0
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)

        min_x = min(min_x, x0)
        max_x = max(max_x, x1)
        min_y = min(min_y, y0)
        max_y = max(max_y, y1)

        items.append({
            'text': text,
            'cx': cx,
            'cy': cy,
            'x0': x0,
            'y0': y0,
            'x1': x1,
            'y1': y1,
            'is_numeric': bool(re.search(r'\d', text))
        })

    width = max_x - min_x
    height = max_y - min_y

    if width <= 0 or height <= 0:
        return " | ".join(item['text'] for item in items)

    x_axis = []
    y_axis = []
    data = []

    for item in items:
        if item['text'] == title:
            continue

        is_bottom = item['cy'] > min_y + height * 0.85
        is_left = item['cx'] < min_x + width * 0.15

        if is_bottom:
            x_axis.append(item)
        elif is_left:
            y_axis.append(item)
        else:
            data.append(item)

    x_axis.sort(key=lambda x: x['cx'])
    y_axis.sort(key=lambda x: x['cy'])
    data.sort(key=lambda x: (not x['is_numeric'], round(x['cy'] / 15.0), x['cx']))

    chart_type_zh = {
        "bar": "柱状图",
        "line": "折线图",
        "pie": "饼图",
        "unknown": "图表"
    }.get(chart_type, "图表")

    desc_parts = [chart_type_zh]
    if x_axis:
        desc_parts.append("X轴：" + ", ".join(item['text'] for item in x_axis))
    if y_axis:
        desc_parts.append("Y轴：" + ", ".join(item['text'] for item in y_axis))
    if data:
        desc_parts.append("数据：" + ", ".join(item['text'] for item in data[:20]))

    return "，".join(desc_parts)


class PaddleVLProvider(BaseVLMProvider):
    def __init__(self, model_client: Any | None = None):
        self.has_paddle = HAS_PADDLE
        self.model_client = model_client
        self._ocr_engine = None

        if not self.has_paddle and self.model_client is None:
            logger.warning("PaddleOCR/PaddleX not found. PaddleVLProvider will return empty results.")

    def _ensure_ocr_engine(self):
        if self._ocr_engine is not None:
            return self._ocr_engine
        from finreportparser.ocr.paddle_ocr import PaddleOcrEngine
        self._ocr_engine = PaddleOcrEngine()
        return self._ocr_engine

    def _run_ocr(self, image_bytes: bytes) -> list:
        try:
            engine = self._ensure_ocr_engine()
            return engine.predict(image_bytes)
        except Exception as e:
            logger.warning(f"PaddleVL OCR failed: {e}")
            return []

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        if not self.has_paddle and self.model_client is None:
            return ChartMeta(
                chart_type="unknown",
                title="Unknown Chart",
                description="[PaddleVL: PaddleOCR/PaddleX not installed. Chart description not available.]",
                data_points=[]
            )

        if self.model_client and hasattr(self.model_client, "describe_chart"):
            return self.model_client.describe_chart(image_bytes)

        lines = self._run_ocr(image_bytes)
        texts = [ln.text for ln in lines if ln.text and ln.text.strip()]

        if not texts:
            return ChartMeta(
                chart_type="unknown",
                title="Chart",
                description="[PaddleVL: no text detected in chart image via OCR]",
                data_points=[]
            )

        chart_type = _heuristic_chart_type(texts)
        title = _extract_title(texts)
        description = _build_structured_description(lines, chart_type, title)
        data_points = [
            {"text": ln.text, "confidence": round(ln.confidence, 4)}
            for ln in lines
            if ln.text and ln.text.strip() and not _is_noise(ln.text)
        ]
        data_points.sort(key=lambda x: not bool(re.search(r'\d', x["text"])))
        data_points = data_points[:20]

        return ChartMeta(
            chart_type=chart_type,
            title=title,
            description=description,
            data_points=data_points
        )

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        if not self.has_paddle and self.model_client is None:
            return []

        if self.model_client and hasattr(self.model_client, "diagram_to_mermaid_candidates"):
            return self.model_client.diagram_to_mermaid_candidates(image_bytes)

        lines = self._run_ocr(image_bytes)
        texts = [ln.text for ln in lines if ln.text and ln.text.strip()]
        if not texts:
            return []

        if not _has_flow_keywords(texts):
            return []

        title = texts[0].strip()[:40] if texts[0].strip() else "Flow"
        safe_title = title.replace('"', "'")
        code = f'graph TD;\n    A["{safe_title}"];\n'
        return [code]

    def unload(self) -> None:
        if self.model_client and hasattr(self.model_client, "unload"):
            self.model_client.unload()
        self.model_client = None
        if self._ocr_engine is not None:
            try:
                self._ocr_engine.unload()
            except Exception as e:
                logger.debug("OCR engine unload failed: %s", e)
        self._ocr_engine = None