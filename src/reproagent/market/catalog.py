"""四个 DataLoader 后端的配置与健康检查。"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Literal

from reproagent.settings import Settings

FeedStatus = Literal["ready", "unconfigured", "missing-package"]


@dataclass(frozen=True)
class FeedSpec:
    id: str
    title: str
    kind: str
    summary: str
    env_keys: tuple[str, ...]


SPECS: tuple[FeedSpec, ...] = (
    FeedSpec(
        id="local",
        title="本地 Parquet",
        kind="parquet",
        summary="prices.parquet（可选 fundamentals / cb_prices），离线复现默认源。",
        env_keys=("DATA_SOURCE", "LOCAL_DATA_PATH"),
    ),
    FeedSpec(
        id="tushare",
        title="Tushare",
        kind="vendor-api",
        summary="A 股日频与 daily_basic；需要 token 与 extra tushare。",
        env_keys=("DATA_SOURCE", "TUSHARE_TOKEN"),
    ),
    FeedSpec(
        id="ricequant",
        title="米筐 rqdatac",
        kind="vendor-api",
        summary="指数成分 as-of、量价与基本面；需要 token 或账号。",
        env_keys=("DATA_SOURCE", "RQ_TOKEN", "RQ_USER", "RQ_PASS"),
    ),
    FeedSpec(
        id="qlib",
        title="Qlib 本地库",
        kind="vendor-bin",
        summary="Qlib .bin 行情目录（DATA_SOURCE=qlib）；extra 安装 pyqlib。",
        env_keys=("DATA_SOURCE", "QLIB_DATA_PATH"),
    ),
)


def _secret_set(value: Any) -> bool:
    if value is None:
        return False
    raw = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
    return bool(str(raw).strip())


def probe_feed(spec: FeedSpec, settings: Settings) -> dict[str, Any]:
    """单个数据源的健康状态。"""
    active = settings.data_source == spec.id
    status: FeedStatus = "unconfigured"
    detail = ""
    if spec.id == "local":
        from pathlib import Path

        root = Path(settings.local_data_path or "tests/fixtures/test_data")
        prices = root / "prices.parquet"
        cb = root / "cb_prices.parquet"
        if prices.is_file() or cb.is_file():
            status = "ready"
            detail = str(root)
        else:
            status = "unconfigured"
            detail = f"missing prices.parquet under {root}"
    elif spec.id == "tushare":
        if importlib.util.find_spec("tushare") is None:
            status = "missing-package"
            detail = "uv sync --extra tushare"
        elif _secret_set(settings.tushare_token):
            status = "ready"
            detail = "token configured"
        else:
            detail = "TUSHARE_TOKEN empty"
    elif spec.id == "ricequant":
        if importlib.util.find_spec("rqdatac") is None:
            status = "missing-package"
            detail = "uv sync --extra ricequant"
        elif _secret_set(settings.ricequant_token) or (
            _secret_set(settings.rq_user) and _secret_set(settings.rq_pass)
        ):
            status = "ready"
            detail = "credentials configured"
        else:
            detail = "RQ_TOKEN or RQ_USER+RQ_PASS empty"
    elif spec.id == "qlib":
        if importlib.util.find_spec("qlib") is None:
            status = "missing-package"
            detail = "uv sync --extra qlib"
        elif settings.qlib_data_path:
            status = "ready"
            detail = str(settings.qlib_data_path)
        else:
            detail = "QLIB_DATA_PATH empty"
    return {
        "id": spec.id,
        "title": spec.title,
        "kind": spec.kind,
        "summary": spec.summary,
        "env_keys": list(spec.env_keys),
        "status": status,
        "detail": detail,
        "active": active,
    }


def probe_feeds(settings: Settings) -> dict[str, Any]:
    items = [probe_feed(spec, settings) for spec in SPECS]
    ready = sum(1 for it in items if it["status"] == "ready")
    return {
        "active": settings.data_source,
        "items": items,
        "ready": ready,
        "count": len(items),
    }
