"""Factor names with slashes must not create nested wiki paths."""

from __future__ import annotations

from reproagent.library.wiki_writer import safe_factor_filename


def test_safe_filename_replaces_slash() -> None:
    assert "/" not in safe_factor_filename("E/P")
    assert "\\" not in safe_factor_filename("EP\\P")
    assert safe_factor_filename("E/P") == "E_P"
    assert safe_factor_filename("Earnings/Price") == "Earnings_Price"


def test_safe_filename_empty() -> None:
    assert safe_factor_filename("") == "factor"
    assert safe_factor_filename("  ///  ") == "factor"
