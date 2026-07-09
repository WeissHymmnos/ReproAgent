"""全局 fixtures（样例 PDF、mock LLM 等，待实现）。"""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_report_path(tmp_path):
    """占位：临时 PDF 路径 fixture。"""
    p = tmp_path / "sample.pdf"
    p.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    return p
