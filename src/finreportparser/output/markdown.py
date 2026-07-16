from finreportparser.fusion.sanitize import sanitize_document_text
from finreportparser.output.frontmatter import build_frontmatter
from finreportparser.types import BlockType, DocumentResult


def render_markdown(doc: DocumentResult) -> str:
    parts = []
    parts.append(build_frontmatter(doc.metadata))

    if hasattr(doc, "toc") and doc.toc:
        parts.append("## 目录\n\n")
        for entry in doc.toc:
            indent = "  " * (entry.level - 1)
            parts.append(f"{indent}- [{entry.title}](#page-{entry.page})\n")
        parts.append("\n")

    for page in doc.pages:
        parts.append(f"<!-- page: {page.page_num} -->\n\n")
        for block in page.blocks:
            if not block.text:
                continue

            if block.type == BlockType.FORMULA:
                if "[Table_" in block.text:
                    sanitized = sanitize_document_text(block.text)
                    if sanitized:
                        parts.append(sanitized)
                        parts.append("\n\n")
                else:
                    latex = block.text
                    parts.append(f"$$\n{latex}\n$$\n\n")
                continue

            if block.type == BlockType.CHART:
                chart_meta = block.metadata.get("chart_meta", {}) if block.metadata else {}
                chart_type = chart_meta.get("chart_type", "unknown")
                title = chart_meta.get("title", "Chart")
                description = block.text
                if description.strip() == "图表，数据：HAITONG":
                    description = "图中主要为图形元素，OCR 文本有限"
                parts.append(f"**[图表: {chart_type}]** {title}\n\n{description}\n\n")
                continue

            sanitized = sanitize_document_text(block.text)
            if sanitized:
                parts.append(sanitized)
                parts.append("\n\n")

    content = "".join(parts).strip()
    if content:
        content += "\n"
    return content
