

def validate_mermaid(code: str) -> bool:
    code = code.strip()
    if not code:
        return False

    valid_starts = [
        "graph", "flowchart", "sequenceDiagram", "classDiagram",
        "stateDiagram", "erDiagram", "gantt", "pie", "requirementDiagram",
        "gitGraph", "C4Context", "mindmap", "timeline", "sankey-beta"
    ]

    first_line = code.split('\n')[0].strip()
    for start in valid_starts:
        if first_line.startswith(start):
            return True

    return False

def mermaid_or_fallback(code: str, fallback_text: str) -> tuple[str | None, str | None]:
    if validate_mermaid(code):
        return code, None
    return None, fallback_text
