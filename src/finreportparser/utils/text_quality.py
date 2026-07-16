def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    non_whitespace_chars = [char for char in text if not char.isspace()]
    if not non_whitespace_chars:
        return 0.0
    cjk_count = sum(1 for char in non_whitespace_chars if '\u4e00' <= char <= '\u9fff')
    return cjk_count / len(non_whitespace_chars)

def is_garbled_chinese(text: str, threshold: float = 0.30) -> bool:
    if not text:
        return False

    garbled_count = 0
    for char in text:
        if char == '\ufffd':
            garbled_count += 1
        elif '\ue000' <= char <= '\uf8ff':
            garbled_count += 1
        elif not char.isprintable() and char not in '\n\r\t':
            garbled_count += 1

    if (garbled_count / len(text)) > threshold:
        return True

    ratio = cjk_ratio(text)
    if ratio > 0.0 and ratio < threshold:
        return True

    return False
