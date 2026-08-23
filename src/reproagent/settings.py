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
    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "llm_api_key",
            "LLM_API_KEY",
        ),
    )
    llm_base_url: str | None = None
    llm_model: str = "claude-sonnet-4-5"
    llm_vision_model: str = "claude-sonnet-4-5"
    llm_temperature: float = 0.0
    llm_seed: int = 42

    # Parser
    parser_backend: Literal["finpdfpro", "marker", "llamaparse", "mineru"] = "finpdfpro"
    parser_version: str = "1.0.0"
    finpdfpro_profile: Literal["auto", "lite", "balanced", "quality"] = "balanced"
    finpdfpro_mode: Literal["fast", "balanced", "max-quality"] | None = None
    finpdfpro_vlm_backend: Literal[
        "none", "paddle_vl", "smolvlm", "edge", "hybrid", "llamacpp_http"
    ] = "none"
    finpdfpro_formula_backend: Literal["none", "l0", "l1", "pix2text", "auto"] = "l1"

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

    # 运行环境：prod 下默认禁止 mock LLM 与公式静默降级
    app_env: Literal["dev", "prod"] = "dev"
    # None = 跟随 app_env（dev 允许 / prod 禁止）；显式 True/False 覆盖
    allow_mock_llm: bool | None = None
    allow_formula_fallback: bool | None = None

    # TUI
    tui_theme: str = "dark"

    # Research memory
    memory_enabled: bool = True
    skip_mock_reflection: bool = False

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def mock_llm_allowed(self) -> bool:
        if self.allow_mock_llm is not None:
            return self.allow_mock_llm
        return not self.is_prod

    @property
    def formula_fallback_allowed(self) -> bool:
        """不可解析公式时是否静默退回 close（仅 dev 默认允许）。"""
        if self.allow_formula_fallback is not None:
            return self.allow_formula_fallback
        return not self.is_prod

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
