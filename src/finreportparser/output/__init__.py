from pathlib import Path

from finreportparser.output.json_writer import render_json
from finreportparser.output.markdown import render_markdown
from finreportparser.types import DocumentResult


def write_document(
    doc: DocumentResult,
    out_dir: Path,
    stem: str | None = None,
    sidecar: bool = False,
    pdf_path: Path | None = None,
) -> tuple[Path, Path]:
    if not stem:
        if pdf_path:
            stem = pdf_path.stem
        else:
            stem = Path(doc.metadata.source).stem

    if sidecar:
        if pdf_path:
            target_dir = pdf_path.parent
        else:
            source_path = Path(doc.metadata.source)
            if source_path.parent != Path('.'):
                target_dir = source_path.parent
            else:
                target_dir = out_dir
    else:
        target_dir = out_dir / stem

    target_dir.mkdir(parents=True, exist_ok=True)

    md_path = target_dir / f"{stem}.md"
    json_path = target_dir / f"{stem}.json"

    md_content = render_markdown(doc)
    json_content = render_json(doc)

    md_path.write_text(md_content, encoding="utf-8")
    json_path.write_text(json_content, encoding="utf-8")

    return md_path, json_path
