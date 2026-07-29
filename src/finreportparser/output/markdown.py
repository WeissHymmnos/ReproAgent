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

            # Skip blocks already classified as header/footer
            if block.type in (BlockType.HEADER, BlockType.FOOTER):
                continue

            if block.type == BlockType.CHART:
                chart_meta = block.metadata.get("chart_meta", {}) if block.metadata else {}
                chart_type = chart_meta.get("chart_type", "unknown")
                title = chart_meta.get("title", "Chart")
                description = block.text
                # Drop logo-only chart blocks (broker headers)
                from finreportparser.fusion.headers_footers import is_header_footer_block

                if is_header_footer_block(block):
                    continue
                if description.strip() == "图表，数据：HAITONG":
                    description = "图中主要为图形元素，OCR 文本有限"
                # Classify-first metadata line
                cls = chart_meta.get("classification") or {}
                conf = cls.get("confidence")
                src = cls.get("source")
                rationale = cls.get("rationale")
                cls_bits = [f"type={chart_type}"]
                if conf is not None:
                    try:
                        cls_bits.append(f"conf={float(conf):.2f}")
                    except (TypeError, ValueError):
                        pass
                if src:
                    cls_bits.append(f"source={src}")
                if rationale:
                    cls_bits.append(f"why={rationale}")
                header = f"**[图表: {chart_type}]** {title}"
                if len(cls_bits) > 1:
                    header += f"  \n<!-- classify: {' '.join(cls_bits)} -->"
                parts.append(f"{header}\n\n{description}\n\n")
                continue

            sanitized = sanitize_document_text(block.text)
            if sanitized:
                parts.append(sanitized)
                parts.append("\n\n")

    content = "".join(parts).strip()
    if content:
        content += "\n"
    return content
