"""行情带与数据源健康检查。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from reproagent.market.catalog import probe_feeds
from reproagent.market.tape import (
    build_market_snapshot,
    last_session_quotes,
    pulse_from_quotes,
)
from reproagent.settings import Settings
from reproagent.web.app import WebApp

FIXTURE = Path("tests/fixtures/test_data")


def test_last_session_quotes_from_fixture_panel() -> None:
    panel = pl.read_parquet(FIXTURE / "prices.parquet")
    quotes = last_session_quotes(panel, limit=10, spark_bars=8)
    assert len(quotes) == 2
    assets = {q["asset"] for q in quotes}
    assert "000001.SZ" in assets
    assert "600000.SH" in assets
    for q in quotes:
        assert q["close"] is not None
        assert q["session"] == "2023-02-10"
        assert q["chg_pct"] is not None
        assert len(q["spark"]) >= 2
    pulse = pulse_from_quotes(quotes)
    assert pulse["n_assets"] == 2
    assert pulse["n_up"] + pulse["n_down"] + pulse["n_flat"] == 2
    assert pulse["gainer"] is not None
    assert pulse["loser"] is not None


def test_probe_feeds_marks_local_ready() -> None:
    settings = Settings(data_source="local", local_data_path=FIXTURE)
    out = probe_feeds(settings)
    assert out["active"] == "local"
    assert out["count"] == 4
    by_id = {it["id"]: it for it in out["items"]}
    assert by_id["local"]["status"] == "ready"
    assert by_id["local"]["active"] is True
    assert by_id["tushare"]["active"] is False
    assert by_id["qlib"]["status"] in {"unconfigured", "missing-package"}


def test_build_snapshot_uses_dataloader(tmp_path: Path) -> None:
    settings = Settings(
        data_source="local",
        local_data_path=FIXTURE,
        data_dir=tmp_path / "data",
    )
    snap = build_market_snapshot(settings, universe="all", limit=5)
    assert snap["data_source"] == "local"
    assert snap["rows"] > 0
    assert snap["quotes"]
    assert snap["pulse"]["session"]


def test_web_feeds_and_quotes_routes(tmp_path: Path) -> None:
    settings = Settings(
        data_source="local",
        local_data_path=FIXTURE,
        data_dir=tmp_path / "web",
    )
    app = WebApp.from_settings(settings)
    feeds = app.handle("GET", "/api/feeds")
    assert feeds.status == 200
    body = __import__("json").loads(feeds.body)
    assert body["active"] == "local"
    assert any(it["id"] == "local" and it["status"] == "ready" for it in body["items"])

    quotes = app.handle("GET", "/api/market/quotes?limit=2")
    assert quotes.status == 200
    tape = __import__("json").loads(quotes.body)
    assert tape["data_source"] == "local"
    assert len(tape["quotes"]) == 2
    assert "chg_pct" in tape["quotes"][0]


def test_web_market_limit_validation(tmp_path: Path) -> None:
    settings = Settings(
        data_source="local",
        local_data_path=FIXTURE,
        data_dir=tmp_path / "web2",
    )
    app = WebApp.from_settings(settings)
    bad = app.handle("GET", "/api/market/quotes?limit=nope")
    assert bad.status == 400
    assert "limit" in __import__("json").loads(bad.body)["error"]
