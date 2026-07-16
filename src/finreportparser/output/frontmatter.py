import yaml

from finreportparser.types import DocumentMetadata


def build_frontmatter(metadata: DocumentMetadata) -> str:
    data = {
        "title": metadata.title,
        "source": metadata.source,
        "mode": metadata.mode.value if hasattr(metadata.mode, "value") else str(metadata.mode),
    }
    if metadata.created_at:
        data["created_at"] = metadata.created_at

    yaml_str = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_str}---\n"
