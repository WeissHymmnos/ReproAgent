import re


def strip_broker_template_tags(text: str) -> str:
    if not text:
        return text

    text = re.sub(r'\[Table_[A-Za-z0-9_]+\]', '', text)
    text = re.sub(r'\\\[Table_[A-Za-z0-9_]+\\\]', '', text)

    return text.strip()

def strip_repeated_headers_footers(text: str) -> str:
    if not text:
        return text

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            cleaned_lines.append(line)
            continue

        if stripped.startswith('|') and stripped.endswith('|'):
            cells = stripped.split('|')
            cleaned_cells = []
            for i, cell in enumerate(cells):
                if i == 0 or i == len(cells) - 1:
                    cleaned_cells.append(cell)
                    continue

                cell_stripped = cell.strip()

                if cell_stripped == 'HAITONG':
                    cleaned_cells.append(' ' * len(cell))
                elif cell_stripped == '海通证券':
                    cleaned_cells.append(' ' * len(cell))
                elif cell_stripped in ['金融工程研究', '证券研究报告', '金融工程专题报告']:
                    cleaned_cells.append(' ' * len(cell))
                elif cell_stripped.startswith('请务必阅读正文之后'):
                    cleaned_cells.append(' ' * len(cell))
                elif re.match(r'^[-—\s]*\d+[-—\s]*$', cell_stripped):
                    cleaned_cells.append(' ' * len(cell))
                else:
                    cleaned_cells.append(cell)

            cleaned_lines.append('|'.join(cleaned_cells))
            continue

        if stripped == 'HAITONG':
            continue
        if stripped == '海通证券':
            continue
        if stripped in ['金融工程研究', '证券研究报告', '金融工程专题报告']:
            continue

        if stripped.startswith('请务必阅读正文之后'):
            continue

        if re.match(r'^[-—\s]*\d+[-—\s]*$', stripped):
            continue

        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)

def sanitize_document_text(text: str) -> str:
    if not text:
        return text

    text = strip_broker_template_tags(text)
    text = strip_repeated_headers_footers(text)
    # Light OCR phrase cleanup for residual text blocks (tables go through
    # table_repair which applies the full lexicon + structural fixes).
    try:
        from finreportparser.fusion.table_repair import apply_ocr_phrase_fixes

        text = apply_ocr_phrase_fixes(text)
    except Exception:
        pass

    return text
