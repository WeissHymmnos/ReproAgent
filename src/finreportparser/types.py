from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class BlockType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CHART = "chart"
    MERMAID = "mermaid"
    HEADER = "header"
    FOOTER = "footer"
    HEADING = "heading"
    FORMULA = "formula"

class QualityMode(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    MAX_QUALITY = "max-quality"

class TableBackend(StrEnum):
    PADDLE = "paddle"
    MINERU = "mineru"

class VlmBackend(StrEnum):
    NONE = "none"
    PADDLE_VL = "paddle_vl"
    SMOLVLM = "smolvlm"
    LLAMACPP_HTTP = "llamacpp_http"
    # Edge hybrid: small VLM classify + Paddle OCR describe
    EDGE = "edge"

class PageClass(StrEnum):
    BLANK = "blank"
    TEXT_RICH = "text_rich"
    SCANNED = "scanned"
    TABLE_CANDIDATE = "table_candidate"
    CHART_CANDIDATE = "chart_candidate"
    MIXED = "mixed"


class ChartType(StrEnum):
    """Canonical chart/diagram taxonomy used by classify-first pipeline."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    FRAMEWORK = "framework"  # multi-panel methodology / roadmap cards
    FLOWCHART = "flowchart"
    TABLE = "table"
    OTHER = "other"
    UNKNOWN = "unknown"


class ChartClassification(BaseModel):
    """Result of chart classification (before description)."""

    chart_type: ChartType = ChartType.UNKNOWN
    confidence: float = 0.0
    # Where the decision came from: vlm | ocr | fusion
    source: Literal["vlm", "ocr", "fusion"] = "fusion"
    vlm_type: ChartType | None = None
    vlm_confidence: float | None = None
    ocr_type: ChartType | None = None
    ocr_confidence: float | None = None
    labels_considered: list[str] = Field(default_factory=list)
    rationale: str | None = None

class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

class TableExtract(BaseModel):
    gfm: str
    bbox: BBox | None = None
    html: str | None = None

class PageBlock(BaseModel):
    type: BlockType
    bbox: BBox | None = None
    text: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] | None = None

class TableBlock(BaseModel):
    bbox: BBox | None = None
    markdown: str
    confidence: float | None = None
    backend: TableBackend | None = None
    rows: int | None = None
    cols: int | None = None

class ImageRegion(BaseModel):
    bbox: BBox
    image_path: str | None = None
    image_bytes: bytes | None = None
    caption: str | None = None

class ChartMeta(BaseModel):
    bbox: BBox | None = None
    chart_type: str | None = None
    description: str
    title: str | None = None
    data_points: list[dict[str, Any]] | None = None
    # Optional classify-first metadata (serialized into block.metadata)
    classification: ChartClassification | None = None

class MermaidBlock(BaseModel):
    bbox: BBox | None = None
    code: str
    fallback_text: str | None = None

class FormulaMeta(BaseModel):
    latex: str
    source: Literal["l1", "pix2text", "paddle_formula", "unknown"]
    display: bool = True
    confidence: float | None = None
    eq_number: str | None = None

class MetricItem(BaseModel):
    name: str
    raw_name: str
    value: float | None = None
    unit: str | None = None
    raw_value: str
    yoy: float | None = None
    qoq: float | None = None
    page_num: int | None = None

Metrics = MetricItem

class NumberSpan(BaseModel):
    value: float
    unit: str | None = None
    raw_text: str
    start_idx: int
    end_idx: int

class PageResult(BaseModel):
    page_num: int
    blocks: list[PageBlock] = Field(default_factory=list)
    classification: PageClass | None = None
    needs_ocr: bool = False
    width: float | None = None
    height: float | None = None

class DocumentMetadata(BaseModel):
    title: str | None = None
    source: str
    mode: QualityMode
    created_at: str | None = None

class TocEntry(BaseModel):
    level: int
    title: str
    page: int

class DocumentResult(BaseModel):
    metadata: DocumentMetadata
    pages: list[PageResult] = Field(default_factory=list)
    metrics: list[MetricItem] = Field(default_factory=list)
    charts: list[ChartMeta] = Field(default_factory=list)
    mermaid: list[MermaidBlock] = Field(default_factory=list)
    toc: list[TocEntry] = Field(default_factory=list)
    quality: dict[str, Any] | None = None
