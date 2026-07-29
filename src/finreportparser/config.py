import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    mode: Literal["fast", "balanced", "max-quality"]
    workers: int = Field(default=1, ge=1)
    ocr_backend: Literal["paddle", "unlimited-ocr"] = "paddle"
    table_backend: Literal["paddle", "mineru", "unlimited-ocr"] = "paddle"
    vlm_backend: Literal[
        "none", "paddle_vl", "smolvlm", "llamacpp_http", "unlimited-ocr", "edge", "hybrid"
    ] = "none"
    formula_backend: Literal["none", "l1", "pix2text", "auto"] = "auto"
    image_max_edge: int = Field(default=640, ge=512, le=1024)
    resume: bool = True
    out_dir: str = "./output"
    sidecar: bool = False
    cache_dir: str | None = None
    model_dir: str = "~/.cache/finreportparser/models"
    cpu_threads: int = 4
    enable_hpi: bool = False
    # Cap chart VLM calls per page (logos/headers skipped by area filter too)
    max_vlm_images: int = Field(default=3, ge=0, le=20)
    # --- Speed / quality / load controls ---
    prefer_text_tables: bool = True
    allow_structure: bool = True
    structure_only_if_text_weak: bool = True
    allow_ocr: bool = True
    allow_vlm: bool = False
    strip_headers_footers: bool = True
    # Minimum table quality score to accept text-layer tables (skip structure)
    text_table_min_score: float = Field(default=0.45, ge=0.0, le=1.0)

    @field_validator("model_dir")
    @classmethod
    def expand_model_dir(cls, v: str) -> str:
        return os.path.expanduser(v)

    @field_validator("cache_dir")
    @classmethod
    def expand_cache_dir(cls, v: str | None) -> str | None:
        if v is not None:
            return os.path.expanduser(v)
        return v

def find_configs_dir() -> Path:
    current_file_dir = Path(__file__).resolve().parent
    # 1) package-local: finreportparser/configs
    candidate = current_file_dir / "configs"
    if candidate.is_dir():
        return candidate
    # 2) src layout repo root: .../src/finreportparser/config.py -> parent.parent.parent / configs
    for cand in (
        current_file_dir.parent.parent / "configs",
        current_file_dir.parent.parent.parent / "configs",
    ):
        if cand.is_dir():
            return cand
    # 3) cwd and parents (existing fallback)
    cwd = Path.cwd()
    if (cwd / "configs").is_dir():
        return cwd / "configs"
    for parent in cwd.parents:
        if (parent / "configs").is_dir():
            return parent / "configs"
    return current_file_dir / "configs"

def load_config(path: str | None = None, overrides: dict | None = None) -> Config:
    configs_dir = find_configs_dir()
    overrides = dict(overrides or {})

    # Named profile (lite|balanced|quality) expands first; CLI flags still win.
    profile_name = overrides.pop("profile", None)
    profile_data: dict = {}
    if profile_name:
        from finreportparser.profiles import resolve_profile

        profile_data = resolve_profile(str(profile_name))

    if path is not None:
        config_path = Path(path)
    else:
        mode = profile_data.get("mode") or overrides.get("mode") or "balanced"
        if mode == "balanced":
            filename = "default.yaml"
        elif mode == "fast":
            filename = "fast.yaml"
        elif mode == "max-quality":
            filename = "max_quality.yaml"
        else:
            filename = "default.yaml"

        config_path = configs_dir / filename

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    # Precedence: yaml < profile < explicit overrides
    config_data.update(profile_data)
    config_data.update(overrides)

    return Config(**config_data)
