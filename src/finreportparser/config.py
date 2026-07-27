import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    mode: Literal["fast", "balanced", "max-quality"]
    workers: int = Field(default=2, ge=1)
    ocr_backend: Literal["paddle", "unlimited-ocr"] = "paddle"
    table_backend: Literal["paddle", "mineru", "unlimited-ocr"]
    vlm_backend: Literal[
        "none", "paddle_vl", "smolvlm", "llamacpp_http", "unlimited-ocr", "edge", "hybrid"
    ]
    formula_backend: Literal["none", "l1", "pix2text", "auto"] = "auto"
    image_max_edge: int = Field(default=768, ge=512, le=768)
    resume: bool = True
    out_dir: str = "./output"
    sidecar: bool = False
    cache_dir: str | None = None
    model_dir: str = "~/.cache/finreportparser/models"
    cpu_threads: int = 4
    enable_hpi: bool = False

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

    if path is not None:
        config_path = Path(path)
    else:
        mode = "balanced"
        if overrides and "mode" in overrides:
            mode = overrides["mode"]

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

    if overrides:
        config_data.update(overrides)

    return Config(**config_data)
