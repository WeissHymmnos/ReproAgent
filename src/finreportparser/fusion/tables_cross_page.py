import logging
import re

from finreportparser.types import BlockType, PageResult

logger = logging.getLogger(__name__)

def _get_table_columns(markdown: str) -> int:
    lines = markdown.strip().split('\n')
    if not lines:
        return 0
    return lines[0].count('|') - 1

def _get_table_header(markdown: str) -> str:
    lines = markdown.strip().split('\n')
    if not lines:
        return ""
    return lines[0]

def _normalize_header(header: str) -> str:
    header = header.replace('|', '')
    return re.sub(r'\s+', '', header)

def _pad_table_columns(table: str, target_cols: int) -> str:
    lines = table.strip().split('\n')
    padded_lines = []
    for i, line in enumerate(lines):
        if not line.strip():
            padded_lines.append(line)
            continue

        line = line.strip()
        if not line.startswith('|'):
            line = '| ' + line
        if not line.endswith('|'):
            line = line + ' |'

        current_cols = line.count('|') - 1

        if current_cols < target_cols:
            diff = target_cols - current_cols
            if i == 1 and set(line.replace('|', '').replace('-', '').replace(' ', '')) == set():
                padding = '---|' * diff
            else:
                padding = '   |' * diff

            padded_lines.append(line + padding)
        else:
            padded_lines.append(line)

    return '\n'.join(padded_lines)

def _merge_markdown_tables(table1: str, table2: str) -> str:
    lines1 = table1.strip().split('\n')
    lines2 = table2.strip().split('\n')

    if len(lines2) > 2 and set(lines2[1].strip().replace('|', '').replace('-', '').replace(' ', '')) == set():
        lines2 = lines2[2:]
    elif len(lines2) > 1 and '|' in lines2[0]:
        lines2 = lines2[1:]

    return '\n'.join(lines1 + lines2)

def merge_continued_tables(pages: list[PageResult]) -> list[PageResult]:
    if not pages:
        return pages

    merged_any = True
    while merged_any:
        merged_any = False

        for i in range(len(pages)):
            current_page = pages[i]
            if not current_page.blocks:
                continue

            next_page_idx = -1
            for j in range(i + 1, len(pages)):
                if pages[j].blocks:
                    next_page_idx = j
                    break

            if next_page_idx == -1:
                continue

            next_page = pages[next_page_idx]

            last_block = current_page.blocks[-1]
            first_block = next_page.blocks[0]

            if last_block.type == BlockType.TABLE and first_block.type == BlockType.TABLE:
                if last_block.text and first_block.text:
                    cols1 = _get_table_columns(last_block.text)
                    cols2 = _get_table_columns(first_block.text)

                    header1 = _get_table_header(last_block.text)
                    header2 = _get_table_header(first_block.text)

                    norm_header1 = _normalize_header(header1)
                    norm_header2 = _normalize_header(header2)

                    if norm_header1 == norm_header2:
                        if cols1 != cols2:
                            logger.warning(
                                f"Column count mismatch between tables on page {current_page.page_num} "
                                f"({cols1} cols) and {next_page.page_num} ({cols2} cols). Attempting reconciliation."
                            )
                            target_cols = max(cols1, cols2)
                            if cols1 < target_cols:
                                last_block.text = _pad_table_columns(last_block.text, target_cols)
                                cols1 = target_cols
                            if cols2 < target_cols:
                                first_block.text = _pad_table_columns(first_block.text, target_cols)
                                cols2 = target_cols

                        if cols1 > 0:
                            merged_text = _merge_markdown_tables(last_block.text, first_block.text)

                            last_block.text = merged_text
                            if not last_block.metadata:
                                last_block.metadata = {}

                            source_pages = last_block.metadata.get('source_pages', [current_page.page_num])
                            if first_block.metadata:
                                next_source_pages = first_block.metadata.get(
                                    'source_pages', [next_page.page_num]
                                )
                            else:
                                next_source_pages = [next_page.page_num]
                            for p in next_source_pages:
                                if p not in source_pages:
                                    source_pages.append(p)
                            last_block.metadata['source_pages'] = source_pages

                            next_page.blocks.pop(0)
                            merged_any = True
                            break

    return pages
