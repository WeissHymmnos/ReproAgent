import importlib.util
import logging
import re
from typing import Any

from finreportparser.types import ChartClassification, ChartMeta, ChartType
from finreportparser.vlm.chart_classify import ocr_prior_from_lines

logger = logging.getLogger(__name__)

HAS_PADDLE = importlib.util.find_spec("paddleocr") is not None

_FLOW_KEYWORDS = (
    "流程",
    "步骤",
    "→",
    "->",
    "flowchart",
    "flow",
    "演进",
    "路径",
    "阶段",
    "框架",
    "方法论",
    "第一阶段",
    "第二阶段",
    "第三阶段",
    "智能体",
    "奖励反馈",
    "初始种群",
)
_NOISE_KEYWORDS = {
    "haitong",
    "海通证券",
    "证券研究报告",
    "金融工程研究",
    "请务必阅读",
    "资料来源",
    "数据来源",
    "chatgp",
    "chatgpt",
    "华泰研究",
}


def _is_noise(text: str) -> bool:
    text_lower = text.lower().strip()
    if any(kw in text_lower for kw in _NOISE_KEYWORDS):
        return True
    if len(text_lower) < 2:
        if not re.match(r"^[\d%]+$", text_lower):
            return True
    return False


def _extract_title(texts: list[str]) -> str:
    for text in texts:
        if re.search(r"^(图|图表|Figure)\s*\d+", text, re.IGNORECASE):
            return text.strip()[:120]
    return texts[0].strip()[:120] if texts else "Chart"


def _has_flow_keywords(texts: list[str]) -> bool:
    joined = " ".join(texts)
    return any(kw in joined for kw in _FLOW_KEYWORDS)


def _line_items(lines: list[Any], title: str) -> list[dict]:
    items = []
    for ln in lines:
        if not getattr(ln, "bbox", None) or len(ln.bbox) != 4:
            continue
        text = (ln.text or "").strip()
        if not text or _is_noise(text) or text == title:
            continue
        xs = [p[0] for p in ln.bbox]
        ys = [p[1] for p in ln.bbox]
        items.append(
            {
                "text": text,
                "cx": sum(xs) / 4.0,
                "cy": sum(ys) / 4.0,
                "x0": min(xs),
                "y0": min(ys),
                "x1": max(xs),
                "y1": max(ys),
                "is_numeric": bool(re.search(r"\d", text)),
                "confidence": float(getattr(ln, "confidence", 1.0) or 1.0),
            }
        )
    return items


def _reading_order_lines(items: list[dict], row_tol: float = 14.0) -> list[str]:
    """Cluster by Y then left-to-right — good for framework / multi-column cards."""
    if not items:
        return []
    sorted_items = sorted(items, key=lambda x: (x["cy"], x["cx"]))
    rows: list[list[dict]] = []
    for it in sorted_items:
        if not rows:
            rows.append([it])
            continue
        if abs(it["cy"] - rows[-1][0]["cy"]) <= row_tol:
            rows[-1].append(it)
        else:
            rows.append([it])
    lines_out = []
    for row in rows:
        row.sort(key=lambda x: x["cx"])
        # merge same-row fragments with space; keep logical separators
        line = " ".join(x["text"] for x in row)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines_out.append(line)
    return lines_out


def _group_by_columns(items: list[dict], n_cols: int = 3) -> list[list[dict]]:
    if not items:
        return []
    min_x = min(i["cx"] for i in items)
    max_x = max(i["cx"] for i in items)
    width = max(max_x - min_x, 1.0)
    cols: list[list[dict]] = [[] for _ in range(n_cols)]
    for it in items:
        idx = min(n_cols - 1, int((it["cx"] - min_x) / width * n_cols))
        cols[idx].append(it)
    for col in cols:
        col.sort(key=lambda x: (x["cy"], x["cx"]))
    return cols


def _build_framework_description(items: list[dict], title: str) -> str:
    """Describe multi-panel methodology / flow diagrams without fake X/Y axes."""
    lines = _reading_order_lines(items)
    if not lines:
        return "框架图（OCR 未识别到有效文本）"

    # Prefer column grouping when layout looks multi-panel (wide + many blocks)
    use_cols = len(items) >= 12
    parts = [f"【框架/流程图】{title}"]

    if use_cols:
        cols = _group_by_columns(items, n_cols=3)
        # Filter empty columns
        cols = [c for c in cols if c]
        if len(cols) >= 2:
            for i, col in enumerate(cols, 1):
                col_lines = _reading_order_lines(col, row_tol=16.0)
                # Keep more content for frameworks
                body = "；".join(col_lines[:18])
                parts.append(f"面板{i}：{body}")
            # Also surface explicit stage headers if present
            stage_hits = [ln for ln in lines if re.search(r"阶段|遗传规划|深度学习|强化学习", ln)]
            if stage_hits:
                parts.append("关键节点：" + " | ".join(stage_hits[:12]))
            return "\n".join(parts)

    # Fallback: reading order bullet list (cap length)
    parts.append("内容（阅读顺序）：")
    for ln in lines[:40]:
        parts.append(f"- {ln}")
    return "\n".join(parts)


def _build_axis_chart_description(items: list[dict], chart_type: str, title: str) -> str:
    min_x = min(i["x0"] for i in items)
    max_x = max(i["x1"] for i in items)
    min_y = min(i["y0"] for i in items)
    max_y = max(i["y1"] for i in items)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0 or height <= 0:
        return " | ".join(i["text"] for i in items[:30])

    x_axis, y_axis, data = [], [], []
    for item in items:
        is_bottom = item["cy"] > min_y + height * 0.85
        is_left = item["cx"] < min_x + width * 0.12
        if is_bottom:
            x_axis.append(item)
        elif is_left:
            y_axis.append(item)
        else:
            data.append(item)

    x_axis.sort(key=lambda x: x["cx"])
    y_axis.sort(key=lambda x: x["cy"])
    data.sort(key=lambda x: (not x["is_numeric"], round(x["cy"] / 15.0), x["cx"]))

    chart_type_zh = {
        "bar": "柱状图",
        "line": "折线图",
        "pie": "饼图",
        "table": "表格图",
        "unknown": "图表",
    }.get(chart_type, "图表")

    desc_parts = [chart_type_zh]
    if title and title not in ("Chart", "图表"):
        desc_parts.append(f"标题：{title}")
    if x_axis:
        desc_parts.append("X轴：" + ", ".join(item["text"] for item in x_axis[:12]))
    if y_axis:
        desc_parts.append("Y轴：" + ", ".join(item["text"] for item in y_axis[:12]))
    if data:
        desc_parts.append("标注：" + ", ".join(item["text"] for item in data[:25]))
    return "；".join(desc_parts)


def _normalize_type(chart_type: str | ChartType) -> str:
    if isinstance(chart_type, ChartType):
        return chart_type.value
    return str(chart_type or "unknown").lower()


def _build_structured_description(lines: list[Any], chart_type: str | ChartType, title: str) -> str:
    ctype = _normalize_type(chart_type)
    items = _line_items(lines, title)
    if not items:
        return "图中主要为图形元素，OCR 未识别到可读标注"

    if len(items) <= 2:
        chart_type_zh = {
            "bar": "柱状图",
            "line": "折线图",
            "pie": "饼图",
            "scatter": "散点图",
            "heatmap": "热力图",
            "framework": "框架/方法论图",
            "flowchart": "流程图",
            "table": "表格图",
            "other": "其他图示",
            "unknown": "图表",
        }.get(ctype, "图表")
        labels = "，".join(it["text"] for it in items)
        return f"{chart_type_zh}，包含标签：{labels}"

    # Framework / flow / dense-text: never invent X/Y axes
    if ctype in ("framework", "flowchart", "other") or (
        ctype == "unknown" and len(items) >= 8
    ):
        return _build_framework_description(items, title)

    if ctype == "table":
        lines_out = _reading_order_lines(items)
        return "表格图内容：\n" + "\n".join(f"- {ln}" for ln in lines_out[:40])

    return _build_axis_chart_description(items, ctype, title)


def _framework_to_mermaid(texts: list[str], title: str) -> list[str]:
    """Build a simple mermaid for stage / method frameworks when possible."""
    stages = []
    for t in texts:
        m = re.search(r"(第[一二三四五六七八九十\d]+阶段[：:]?\s*.{0,20})", t)
        if m:
            stages.append(m.group(1).strip())
    methods = []
    for t in texts:
        if re.search(r"遗传规划|深度学习|强化学习|GP|DL|RL", t):
            methods.append(t.strip()[:40])

    safe_title = (title or "框架").replace('"', "'")[:40]
    if stages:
        nodes = []
        edges = []
        for i, s in enumerate(stages[:6]):
            nid = chr(ord("A") + i)
            nodes.append(f'    {nid}["{s.replace(chr(34), chr(39))}"]')
            if i > 0:
                edges.append(f"    {chr(ord('A') + i - 1)} --> {nid}")
        code = f'graph LR\n    title["{safe_title}"]\n' + "\n".join(nodes + edges)
        return [code]
    if methods:
        nodes = [f'    M{i}["{m.replace(chr(34), chr(39))}"]' for i, m in enumerate(methods[:6])]
        return [f'graph TD\n    T["{safe_title}"]\n' + "\n".join(nodes)]
    return []


class PaddleVLProvider:
    """OCR-centric chart helper (not a true vision LLM).

    Provides OCR text extraction + OCR prior classification. For real visual
    classification use EdgeHybridVLM / SmolVlmProvider.
    """

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

    def classify_chart(self, image_bytes: bytes) -> ChartClassification | None:
        """OCR-only soft prior (source=ocr)."""
        if self.model_client and hasattr(self.model_client, "classify_chart"):
            return self.model_client.classify_chart(image_bytes)
        if not self.has_paddle:
            return ChartClassification(
                chart_type=ChartType.UNKNOWN,
                confidence=0.0,
                source="ocr",
                rationale="paddle_unavailable",
            )
        lines = self._run_ocr(image_bytes)
        ctype, conf, why = ocr_prior_from_lines(lines)
        return ChartClassification(
            chart_type=ctype,
            confidence=conf,
            source="ocr",
            ocr_type=ctype,
            ocr_confidence=conf,
            rationale=why,
        )

    def describe_chart_as(
        self, image_bytes: bytes, chart_type: str | ChartType
    ) -> ChartMeta | None:
        """Describe using a pre-assigned chart type (classify-first)."""
        if not self.has_paddle and self.model_client is None:
            return ChartMeta(
                chart_type=_normalize_type(chart_type),
                title="Unknown Chart",
                description="[PaddleVL: PaddleOCR/PaddleX not installed. Chart description not available.]",
                data_points=[],
            )

        lines = self._run_ocr(image_bytes)
        texts = [ln.text for ln in lines if ln.text and ln.text.strip()]
        if not texts:
            return ChartMeta(
                chart_type=_normalize_type(chart_type),
                title="Chart",
                description="[PaddleVL: no text detected in chart image via OCR]",
                data_points=[],
            )
        title = _extract_title(texts)
        description = _build_structured_description(lines, chart_type, title)
        data_points = [
            {"text": ln.text, "confidence": round(ln.confidence, 4)}
            for ln in lines
            if ln.text and ln.text.strip() and not _is_noise(ln.text)
        ]
        data_points.sort(key=lambda x: -x["confidence"])
        return ChartMeta(
            chart_type=_normalize_type(chart_type),
            title=title,
            description=description,
            data_points=data_points[:40],
        )

    def describe_chart(self, image_bytes: bytes) -> ChartMeta | None:
        if self.model_client and hasattr(self.model_client, "describe_chart"):
            return self.model_client.describe_chart(image_bytes)

        # OCR-only path: classify (OCR prior) then describe
        cls = self.classify_chart(image_bytes)
        ctype = cls.chart_type if cls else ChartType.UNKNOWN
        meta = self.describe_chart_as(image_bytes, ctype)
        if meta is not None and cls is not None:
            meta.classification = cls
        return meta

    def diagram_to_mermaid_candidates(self, image_bytes: bytes) -> list[str]:
        if not self.has_paddle and self.model_client is None:
            return []

        if self.model_client and hasattr(self.model_client, "diagram_to_mermaid_candidates"):
            return self.model_client.diagram_to_mermaid_candidates(image_bytes)

        lines = self._run_ocr(image_bytes)
        texts = [ln.text for ln in lines if ln.text and ln.text.strip()]
        if not texts:
            return []

        title = _extract_title(texts)
        cls = self.classify_chart(image_bytes)
        if cls and cls.chart_type in (ChartType.FRAMEWORK, ChartType.FLOWCHART):
            return _framework_to_mermaid(texts, title)
        if _has_flow_keywords(texts):
            return _framework_to_mermaid(texts, title)
        return []

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
