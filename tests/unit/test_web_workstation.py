"""Web workstation: payload builders + HTTP handlers (real entry points)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from reproagent.ingestion.review_queue import enqueue_manual_review
from reproagent.library.manager import FactorLibraryManager
from reproagent.models.factor_def import FactorDefinition
from reproagent.models.library import FactorLibraryEntry
from reproagent.models.report import ResearchReport
from reproagent.persistence.db import get_engine, init_db
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository
from reproagent.settings import Settings
from reproagent.web.app import WebApp, start_background_server
from reproagent.web.payloads import (
    build_library_detail,
    build_library_list,
    build_review_list,
    build_summary,
)
from reproagent.web.workstation import get_index_html


def _settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    # Settings fields vary; construct with overrides commonly used in tests.
    s = Settings()
    object.__setattr__(s, "data_dir", data) if False else None
    # pydantic settings may be frozen-ish — use model_copy if available
    try:
        return s.model_copy(update={"data_dir": data})
    except Exception:
        s.data_dir = data  # type: ignore[misc]
        return s


def _seed_manager(tmp_path: Path, *, name: str = "momentum_ret") -> tuple[FactorLibraryManager, Repository, str]:
    db = tmp_path / "web.db"
    engine = get_engine(db)
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths(data_dir=tmp_path / "data")
    paths.ensure_layout()
    manager = FactorLibraryManager(repository=repo, paths=paths)

    report = ResearchReport(
        id="rep-web-1",
        file_path=tmp_path / "sample.pdf",
        file_hash="hash-web-1",
        title="Web Seed Report",
        author=None,
        broker="HT",
        report_date=None,
        page_count=1,
        validation_status="valid",
        validation_errors=[],
        ingested_at=datetime.now(UTC),
    )
    repo.save_report(report)

    formula = "close / Ref(close, 20) - 1"
    factor = FactorDefinition(
        id=f"id-{name}",
        spec_id=f"spec-{name}",
        name=name,
        name_cn="动量因子样例",
        style="momentum",
        formula=formula,
        input_fields=["close"],
        universe="all",
        rebalance_frequency="monthly",
    )
    entry = FactorLibraryEntry(
        id=f"entry-{name}",
        factor=factor,
        report_id=report.id,
        config_id="cfg1",
        backtest_result_id="bt1",
        deviation_passed=True,
        status="ready",
        version="0.1.0",
        dedup_hash="",
        tags=["web-test"],
        created_at=datetime.now(UTC),
    )
    saved = manager.register(entry)
    return manager, repo, saved.id


def test_build_library_list_empty(tmp_path: Path) -> None:
    engine = get_engine(tmp_path / "empty.db")
    init_db(engine)
    repo = Repository(engine)
    paths = AppPaths(data_dir=tmp_path / "data")
    paths.ensure_layout()
    manager = FactorLibraryManager(repository=repo, paths=paths)
    payload = build_library_list(manager)
    assert payload["count"] == 0
    assert payload["empty"] is True
    assert payload["items"] == []


def test_build_library_list_and_detail_seeded(tmp_path: Path) -> None:
    manager, _repo, entry_id = _seed_manager(tmp_path, name="seed_alpha")
    payload = build_library_list(manager)
    assert payload["count"] == 1
    assert payload["empty"] is False
    assert payload["items"][0]["name"] == "seed_alpha"
    assert payload["items"][0]["formula"]
    assert "close" in payload["items"][0]["formula"]

    detail = build_library_detail(manager, entry_id)
    assert detail is not None
    assert detail["name"] == "seed_alpha"
    assert detail["id"] == entry_id

    missing = build_library_detail(manager, "does-not-exist")
    assert missing is None


def test_build_review_list_seeded(tmp_path: Path) -> None:
    manager, repo, _ = _seed_manager(tmp_path)
    empty = build_review_list(repo)
    assert empty["count"] == 0
    assert empty["items"] == []

    report = repo.get_report("rep-web-1")
    assert report is not None
    entry_id = enqueue_manual_review(report, reason="ui-test-reason", repo=repo)
    q = build_review_list(repo)
    assert q["count"] == 1
    assert q["items"][0]["entry_id"] == entry_id
    assert q["items"][0]["reason"] == "ui-test-reason"
    assert q["items"][0]["title"] == "Web Seed Report"

    summary = build_summary(manager, repo)
    assert summary["library_count"] == 1
    assert summary["review_pending"] == 1


def test_index_html_has_reproagent_sections() -> None:
    html = get_index_html()
    assert "ReproAgent" in html
    assert "因子库" in html
    assert "人工复核" in html
    assert "研报复现" in html
    assert "/api/library" in html
    assert "Swarm Runs" not in html
    assert "Alpha Pool" not in html


def test_webapp_handle_library_and_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, repo, entry_id = _seed_manager(tmp_path, name="http_factor")
    settings = Settings()
    try:
        settings = settings.model_copy(update={"data_dir": tmp_path / "data"})
    except Exception:
        settings.data_dir = tmp_path / "data"  # type: ignore[misc]

    app = WebApp(settings=settings, repository=repo, manager=manager)

    root = app.handle("GET", "/")
    assert root.status == 200
    html = root.body.decode("utf-8")
    assert "因子库" in html and "人工复核" in html

    lib1 = app.handle("GET", "/api/library")
    lib2 = app.handle("GET", "/api/library")
    assert lib1.status == 200 and lib2.status == 200
    data1 = json.loads(lib1.body)
    data2 = json.loads(lib2.body)
    assert data1 == data2
    assert data1["count"] == 1
    assert data1["items"][0]["name"] == "http_factor"
    assert data1["items"][0]["id"] == entry_id

    detail = app.handle("GET", f"/api/library/{entry_id}")
    assert detail.status == 200
    assert json.loads(detail.body)["name"] == "http_factor"

    report = repo.get_report("rep-web-1")
    assert report is not None
    rid = enqueue_manual_review(report, reason="handle-test", repo=repo)
    rev = app.handle("GET", "/api/review")
    assert rev.status == 200
    rev_data = json.loads(rev.body)
    assert rev_data["count"] == 1
    assert rev_data["items"][0]["entry_id"] == rid

    decide = app.handle(
        "POST",
        f"/api/review/{rid}",
        body=json.dumps({"decision": "approve"}).encode(),
    )
    assert decide.status == 200
    after = json.loads(app.handle("GET", "/api/review").body)
    assert after["count"] == 0


def test_live_http_server_twice(tmp_path: Path) -> None:
    manager, repo, entry_id = _seed_manager(tmp_path, name="live_http_factor")
    settings = Settings()
    try:
        settings = settings.model_copy(update={"data_dir": tmp_path / "data"})
    except Exception:
        settings.data_dir = tmp_path / "data"  # type: ignore[misc]
    app = WebApp(settings=settings, repository=repo, manager=manager)
    httpd, base, _ = start_background_server(host="127.0.0.1", port=0, app=app)
    try:
        for _ in range(2):
            with urlopen(base + "/api/library", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            assert body["count"] == 1
            assert body["items"][0]["name"] == "live_http_factor"
            assert body["items"][0]["id"] == entry_id

        with urlopen(base + "/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        assert "ReproAgent" in html
        assert "因子库" in html

        # missing path reproduce → honest error
        req = Request(
            base + "/api/reproduce",
            data=json.dumps({"path": str(tmp_path / "nope.pdf")}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as ei:
            urlopen(req, timeout=5)
        assert ei.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
