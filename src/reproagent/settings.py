"""pydantic-settings 全局配置。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置（环境变量 / .env）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # LLM
    llm_provider: Literal["openai", "anthropic"] = "anthropic"
    llm_api_key: SecretStr = Field(default=SecretStr(""))
    llm_base_url: str | None = None
    llm_model: str = "claude-sonnet-4-5"
    llm_vision_model: str = "claude-sonnet-4-5"
    llm_temperature: float = 0.0
    llm_seed: int = 42

    # Parser
    parser_backend: Literal["finpdfpro", "marker", "llamaparse", "mineru"] = "finpdfpro"
    parser_version: str = "1.0.0"
    finpdfpro_mode: Literal["fast", "balanced", "max-quality"] = "balanced"
    finpdfpro_vlm_backend: Literal["none", "paddle_vl", "smolvlm", "llamacpp_http"] = "none"

    # Data
    data_source: Literal["ricequant", "qlib", "local", "tushare"] = "local"
    ricequant_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ricequant_token", "rq_token", "RICEQUANT_TOKEN", "RQ_TOKEN"),
    )
    rq_user: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("rq_user", "RQ_USER"),
    )
    rq_pass: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("rq_pass", "RQ_PASS"),
    )
    tushare_token: SecretStr | None = None
    qlib_data_path: Path | None = None
    local_data_path: Path | None = None

    # 存储
    data_dir: Path = Field(default_factory=lambda: Path("~/.reproagent").expanduser())

    # 反思
    max_reflection_iterations: int = 3

    # 引擎默认
    default_engine: Literal["polars", "rqalpha"] = "polars"

    # TUI
    tui_theme: str = "dark"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "reproagent.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def factors_dir(self) -> Path:
        return self.data_dir / "factors"

    @property
    def wiki_dir(self) -> Path:
        return self.data_dir / "wiki"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内 Settings 单例。"""
    return Settings()
