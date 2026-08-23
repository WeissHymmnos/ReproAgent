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


def test_upload_junk_pdf_is_invalid_not_crash(tmp_path: Path) -> None:
    from reproagent.ingestion.uploader import upload_pdf
    from reproagent.ingestion.validator import validate_pdf

    junk = tmp_path / "not-a-pdf.pdf"
    junk.write_text("this is not a pdf\n", encoding="utf-8")
    report = upload_pdf(junk)
    assert report.page_count == 0
    report = validate_pdf(report)
    assert report.validation_status == "invalid"
    assert report.validation_errors


def test_ingest_cli_junk_pdf_clean_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    junk = tmp_path / "not-a-pdf.pdf"
    junk.write_text("this is not a pdf\n", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["ingest", str(junk)])
        assert result.exit_code == 1
        out = result.output
        assert "ingest failed" in out
        assert "Traceback" not in out
    finally:
        get_settings.cache_clear()


def test_ingest_cli_same_pdf_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from reproagent.cli import app
    from reproagent.settings import get_settings

    pdf = Path("tests/fixtures/sample_reports/minimal.pdf")
    if not pdf.exists():
        pytest.skip("fixture pdf missing")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        first = runner.invoke(app, ["ingest", str(pdf)])
        second = runner.invoke(app, ["ingest", str(pdf)])
        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert "already ingested" in second.output
        first_id = first.output.split("id=", 1)[1].split()[0]
        second_id = second.output.split("id=", 1)[1].split()[0]
        assert first_id == second_id
    finally:
        get_settings.cache_clear()
