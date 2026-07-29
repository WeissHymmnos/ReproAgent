"""Named quality profiles optimizing the speed / quality / load triangle.

Profiles are presets applied as config overrides. Users can still override
individual flags via CLI.
"""

from __future__ import annotations

from typing import Any

# Three primary profiles for the speed/quality/load product goals.
PROFILES: dict[str, dict[str, Any]] = {
    # Fastest + lightest: text layer only, no OCR/structure/VLM
    "lite": {
        "mode": "fast",
        "table_backend": "paddle",  # unused when allow_structure=false
        "vlm_backend": "none",
        "formula_backend": "none",
        "prefer_text_tables": True,
        "allow_structure": False,
        "allow_ocr": False,
        "allow_vlm": False,
        "max_vlm_images": 0,
        "workers": 1,
        "cpu_threads": 2,
        "image_max_edge": 512,
    },
    # Default production: text tables first; structure only as fallback;
    # OCR only when garbled/scanned; VLM OCR-first for chart pages only.
    "balanced": {
        "mode": "balanced",
        "table_backend": "paddle",
        "vlm_backend": "none",  # charts get OCR-describe via paddle_vl if installed
        "formula_backend": "l1",
        "prefer_text_tables": True,
        "allow_structure": True,
        "structure_only_if_text_weak": True,
        "allow_ocr": True,
        "allow_vlm": False,  # keep load low; use --vlm-backend edge to enable
        "max_vlm_images": 3,
        "workers": 1,
        "cpu_threads": 4,
        "image_max_edge": 640,
    },
    # Best quality: text tables + structure fallback + edge VLM charts
    "quality": {
        "mode": "max-quality",
        "table_backend": "paddle",
        "vlm_backend": "edge",
        "formula_backend": "auto",
        "prefer_text_tables": True,
        "allow_structure": True,
        "structure_only_if_text_weak": False,
        "allow_ocr": True,
        "allow_vlm": True,
        "max_vlm_images": 6,
        "workers": 1,
        "cpu_threads": 4,
        "image_max_edge": 768,
    },
}

# Aliases for CLI convenience
PROFILE_ALIASES: dict[str, str] = {
    "fast": "lite",
    "default": "balanced",
    "max-quality": "quality",
    "max_quality": "quality",
    "hq": "quality",
}


def resolve_profile(name: str | None) -> dict[str, Any]:
    if not name:
        return dict(PROFILES["balanced"])
    key = PROFILE_ALIASES.get(name, name)
    if key not in PROFILES:
        raise ValueError(
            f"Unknown profile {name!r}. Choose from: {', '.join(PROFILES)} "
            f"(aliases: {', '.join(PROFILE_ALIASES)})"
        )
    return dict(PROFILES[key])
