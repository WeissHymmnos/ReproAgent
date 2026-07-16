
def score_table(gfm: str) -> float:
    if not gfm or not gfm.strip():
        return 0.0

    lines = [line.strip() for line in gfm.strip().split('\n') if line.strip()]
    if len(lines) < 3:
        return 0.0

    rows = []
    for line in lines:
        if line.startswith('|') and line.endswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            rows.append(cells)

    if len(rows) < 3:
        return 0.0

    header_row = rows[0]
    data_rows = rows[2:]

    num_cols = len(header_row)
    num_data_rows = len(data_rows)

    if num_data_rows < 2 or num_cols < 2:
        return 0.0

    total_cells = 0
    empty_cells = 0
    total_text_length = 0

    for row in data_rows:
        for cell in row:
            total_cells += 1
            text_len = len(cell)
            total_text_length += text_len
            if text_len == 0:
                empty_cells += 1

            if "请务必阅读正文之后" in cell:
                return 0.0

    if data_rows and data_rows[0]:
        first_cell = data_rows[0][0]
        contamination_keywords = ["HAITONG", "海通证券", "证券研究报告", "金融工程研究"]
        if any(keyword in first_cell for keyword in contamination_keywords):
            return 0.0

    if total_cells == 0:
        return 0.0

    mean_cell_length = total_text_length / total_cells
    if mean_cell_length > 100:
        return 0.0

    empty_ratio = empty_cells / total_cells
    if empty_ratio > 0.7:
        return 0.0

    score = 1.0
    score -= empty_ratio * 0.2
    score -= (mean_cell_length / 100) * 0.2

    return max(0.1, min(1.0, score))

def is_acceptable_table(gfm: str) -> bool:
    return score_table(gfm) > 0.0
