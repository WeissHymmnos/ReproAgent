"""Profile presets and load_config wiring."""

from finreportparser.config import load_config
from finreportparser.profiles import PROFILES, resolve_profile


def test_resolve_profile_names() -> None:
    assert resolve_profile("lite")["allow_structure"] is False
    assert resolve_profile("lite")["allow_vlm"] is False
    assert resolve_profile("balanced")["prefer_text_tables"] is True
    assert resolve_profile("quality")["allow_vlm"] is True
    assert resolve_profile("fast")["mode"] == "fast"  # alias


def test_load_config_profile_lite() -> None:
    cfg = load_config(overrides={"profile": "lite"})
    assert cfg.mode == "fast"
    assert cfg.allow_structure is False
    assert cfg.allow_ocr is False
    assert cfg.allow_vlm is False
    assert cfg.prefer_text_tables is True
    assert cfg.vlm_backend == "none"


def test_load_config_profile_balanced_defaults() -> None:
    cfg = load_config(overrides={"profile": "balanced"})
    assert cfg.prefer_text_tables is True
    assert cfg.structure_only_if_text_weak is True
    assert cfg.allow_structure is True
    # Balanced keeps VLM off by default for low load
    assert cfg.allow_vlm is False or cfg.vlm_backend == "none"


def test_cli_override_beats_profile() -> None:
    cfg = load_config(
        overrides={"profile": "lite", "allow_structure": True, "mode": "balanced"}
    )
    assert cfg.mode == "balanced"
    assert cfg.allow_structure is True


def test_all_profiles_defined() -> None:
    assert set(PROFILES) == {"lite", "balanced", "quality"}
