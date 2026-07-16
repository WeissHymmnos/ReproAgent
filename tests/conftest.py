from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_report_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_reports" / "minimal.pdf"


@pytest.fixture
def prices_parquet_path() -> Path:
    return Path(__file__).parent / "fixtures" / "test_data" / "prices.parquet"
