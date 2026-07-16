from finreportparser.types import DocumentResult


def render_json(doc: DocumentResult) -> str:
    return doc.model_dump_json(indent=2)
