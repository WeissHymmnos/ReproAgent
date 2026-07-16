"""Unit tests for reproagent.utils.pdf helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from reproagent.exceptions import ValidationError
from reproagent.utils.pdf import get_page_count, has_pdf_header, is_readable


def test_get_page_count_fixture(sample_report_path: Path) -> None:
    n = get_page_count(sample_report_path)
    assert isinstance(n, int)
    assert n >= 1


def test_is_readable_fixture(sample_report_path: Path) -> None:
    assert is_readable(sample_report_path) is True


def test_has_pdf_header_fixture(sample_report_path: Path) -> None:
    assert has_pdf_header(sample_report_path) is True


def test_get_page_count_missing(tmp_path: Path) -> None:
    missing = tmp_path / "no_such.pdf"
    with pytest.raises(FileNotFoundError):
        get_page_count(missing)


def test_is_readable_missing(tmp_path: Path) -> None:
    missing = tmp_path / "no_such.pdf"
    with pytest.raises(FileNotFoundError):
        is_readable(missing)


def test_has_pdf_header_missing(tmp_path: Path) -> None:
    missing = tmp_path / "no_such.pdf"
    with pytest.raises(FileNotFoundError):
        has_pdf_header(missing)


def test_get_page_count_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        get_page_count(tmp_path)


def test_has_pdf_header_non_pdf(tmp_path: Path) -> None:
    bad = tmp_path / "not_a_pdf.txt"
    bad.write_bytes(b"hello world, not a pdf header")
    assert has_pdf_header(bad) is False


def test_is_readable_corrupt(tmp_path: Path) -> None:
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot really a pdf body\n")
    result = is_readable(bad)
    assert isinstance(result, bool)