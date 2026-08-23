"""In-process HTTP application for ReproAgent workstation UI."""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from reproagent.library.manager import FactorLibraryManager
from reproagent.persistence.paths import AppPaths
from reproagent.persistence.repository import Repository
from reproagent.settings import Settings, get_settings
from reproagent.web.payloads import (
    build_library_detail,
    build_library_list,
    build_review_list,
    build_summary,
)
from reproagent.web.workstation import get_index_html


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


_ALLOWED_REPORT_SUFFIXES = {".pdf", ".md", ".txt", ".markdown"}


def validate_report_path(raw_path: str) -> tuple[Path | None, str | None]:
    """收窄提交路径：仅接受研报后缀，拒绝任意本地文件探测。

    Returns (path, None) when valid, (None, error_message) otherwise.
    """
    raw = raw_path.strip()
    if not raw:
        return None, "path is required"
    path = Path(raw).expanduser()
    if not path.exists():
        return None, f"path does not exist: {path}"
    if not path.is_file():
        return None, f"path is not a file: {path}"
    if path.suffix.lower() not in _ALLOWED_REPORT_SUFFIXES:
        return (
            None,
            f"unsupported file type: {path.suffix or '(none)'} — "
            f"allowed suffixes: {sorted(_ALLOWED_REPORT_SUFFIXES)}",
        )
    return path, None


def _parse_limit(raw: str | None, *, default: int = 50) -> int | None | HttpResponse:
    """Parse a limit query. Omitted → default; 0 → uncapped; negative → 400."""
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _json({"error": "limit must be an integer"}, status=400)
    if value < 0:
        return _json({"error": "limit must be >= 0"}, status=400)
    if value == 0:
        return None
    return value


def _json(data: Any, status: int = 200) -> HttpResponse:
    from reproagent.utils.jsonutil import dumps as json_dumps

    raw = json_dumps(data).encode("utf-8")
    return HttpResponse(
        status=status,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(raw)),
            "Cache-Control": "no-store",
        },
        body=raw,
    )


def _html(text: str, status: int = 200) -> HttpResponse:
    raw = text.encode("utf-8")
    return HttpResponse(
        status=status,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(raw)),
            "Cache-Control": "no-store",
        },
        body=raw,
    )


def _text(msg: str, status: int = 400) -> HttpResponse:
    raw = msg.encode("utf-8")
    return HttpResponse(
        status=status,
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": str(len(raw)),
        },
        body=raw,
    )


@dataclass
class WebApp:
    """Request router backed by real ReproAgent repository / library manager."""

    settings: Settings
    repository: Repository
    manager: FactorLibraryManager
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> WebApp:
        settings = settings or get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        from reproagent.persistence.db import get_engine, init_db

        engine = get_engine(settings.db_path)
        init_db(engine)
        repo = Repository(engine)
        paths = AppPaths.from_settings(settings)
        paths.ensure_layout()
        manager = FactorLibraryManager(repository=repo, paths=paths)
        return cls(settings=settings, repository=repo, manager=manager)

    def handle(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        query: dict[str, list[str]] | None = None,
    ) -> HttpResponse:
        method = method.upper()
        parsed = urlparse(path)
        route = parsed.path or "/"
        query = query if query is not None else parse_qs(parsed.query)

        try:
            if method == "GET" and route in {"/", "/index.html"}:
                return _html(get_index_html())
            if method == "GET" and route == "/favicon.ico":
                return HttpResponse(
                    status=204,
                    headers={"Cache-Control": "no-store"},
                    body=b"",
                )
            if method == "GET" and route == "/api/health":
                from reproagent import __version__

                return _json({"ok": True, "product": "ReproAgent", "version": __version__})
            if method == "GET" and route == "/api/summary":
                return _json(build_summary(self.manager, self.repository))
            if method == "GET" and route == "/api/library":
                style = (query.get("style") or [None])[0]
                status = (query.get("status") or [None])[0]
                q = (query.get("q") or query.get("query") or [None])[0]
                parsed = _parse_limit((query.get("limit") or [None])[0], default=50)
                if isinstance(parsed, HttpResponse):
                    return parsed
                return _json(
                    build_library_list(
                        self.manager, style=style, status=status, query=q, limit=parsed
                    )
                )
            if method == "GET" and route.startswith("/api/library/"):
                fid = route[len("/api/library/") :].strip("/")
                detail = build_library_detail(self.manager, fid)
                if detail is None:
                    return _json({"error": "not found", "id": fid}, status=404)
                return _json(detail)
            if method == "GET" and route == "/api/review":
                parsed = _parse_limit((query.get("limit") or ["50"])[0], default=50)
                if isinstance(parsed, HttpResponse):
                    return parsed
                return _json(build_review_list(self.repository, limit=parsed))
            if method == "POST" and route.startswith("/api/review/"):
                entry_id = route[len("/api/review/") :].strip("/")
                return self._review_decide(entry_id, body)
            if method == "POST" and route == "/api/reproduce":
                return self._reproduce_submit(body)
            if method == "GET" and route == "/api/jobs":
                with self._lock:
                    items = [dict(job) for job in self.jobs.values()]
                return _json({"items": items, "count": len(items)})
            if method == "GET" and route.startswith("/api/jobs/"):
                job_id = route[len("/api/jobs/") :].strip("/")
                return self._job_status(job_id)
            return _json({"error": "not found", "path": route}, status=404)
        except Exception as exc:  # noqa: BLE001
            payload: dict[str, Any] = {"error": str(exc)}
            if getattr(self.settings, "app_env", "dev") != "prod":
                payload["trace"] = traceback.format_exc(limit=5)
            return _json(payload, status=500)

    def _parse_json(self, body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _review_decide(self, entry_id: str, body: bytes) -> HttpResponse:
        from reproagent.ingestion.review_queue import confirm_manual_review

        try:
            payload = self._parse_json(body)
        except ValueError as exc:
            return _json({"error": str(exc)}, status=400)
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"approve", "reject"}:
            return _json({"error": "decision must be approve or reject"}, status=400)
        from reproagent.exceptions import PersistenceError

        try:
            confirm_manual_review(entry_id, decision, repo=self.repository)  # type: ignore[arg-type]
        except PersistenceError as exc:
            return _json(
                {"error": "review entry not found", "entry_id": entry_id, "detail": str(exc)},
                status=404,
            )
        return _json({"ok": True, "entry_id": entry_id, "decision": decision})

    def _reproduce_submit(self, body: bytes) -> HttpResponse:
        try:
            payload = self._parse_json(body)
        except ValueError as exc:
            return _json({"error": str(exc)}, status=400)
        raw_path = str(payload.get("path") or "").strip()
        path, error = validate_report_path(raw_path)
        if error is not None or path is None:
            return _json({"error": error or "path is required"}, status=400)

        backtest_kwargs = payload.get("backtest_kwargs")
        if backtest_kwargs is not None:
            if not isinstance(backtest_kwargs, dict):
                return _json(
                    {"error": "backtest_kwargs must be an object"}, status=400
                )
            try:
                from datetime import date as date_cls

                from reproagent.models.replication import BacktestParams

                probe = {
                    "start_date": date_cls(2018, 1, 1),
                    "end_date": date_cls(2024, 12, 31),
                    **backtest_kwargs,
                }
                BacktestParams(**probe)
            except Exception as exc:  # noqa: BLE001
                return _json(
                    {"error": f"invalid backtest_kwargs: {exc}"}, status=400
                )

        job_id = uuid.uuid4().hex[:12]
        job: dict[str, Any] = {
            "job_id": job_id,
            "status": "queued",
            "path": str(path),
            "message": "queued",
            "result": None,
            "error": None,
        }
        with self._lock:
            self.jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_reproduce_job,
            args=(job_id, path, backtest_kwargs),
            daemon=True,
            name=f"repro-job-{job_id}",
        )
        thread.start()
        return _json({"job_id": job_id, "status": "queued", "path": str(path)}, status=202)

    def _run_reproduce_job(self, job_id: str, path: Path, backtest_kwargs: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.jobs[job_id]["status"] = "running"
            self.jobs[job_id]["message"] = "pipeline running"

        try:
            from reproagent.pipeline import reproduce_report, reproduce_text

            if path.suffix.lower() in {".md", ".txt"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                result = reproduce_text(
                    text,
                    self.settings,
                    title=path.stem,
                    backtest_kwargs=backtest_kwargs,
                )
            else:
                result = reproduce_report(path, self.settings, backtest_kwargs=backtest_kwargs)

            with self._lock:
                self.jobs[job_id]["status"] = "finished"
                self.jobs[job_id]["message"] = "completed"
                self.jobs[job_id]["result"] = result
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.jobs[job_id]["status"] = "error"
                self.jobs[job_id]["message"] = "failed"
                self.jobs[job_id]["error"] = str(exc)

    def _job_status(self, job_id: str) -> HttpResponse:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None:
                return _json({"error": "job not found", "job_id": job_id}, status=404)
            return _json(dict(job))


def make_handler_class(app: WebApp) -> type:
    """Build a BaseHTTPRequestHandler class bound to ``app``."""
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            # quieter default; still available via server logs if needed
            sys_stderr_write = getattr(self.server, "log_write", None)
            if callable(sys_stderr_write):
                sys_stderr_write("%s - %s\n" % (self.address_string(), fmt % args))

        def _dispatch(self) -> None:
            raw_len = self.headers.get("Content-Length") or "0"
            try:
                length = int(raw_len)
            except (TypeError, ValueError):
                length = -1
            if length < 0 or length > 20_000_000:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "invalid Content-Length"}')
                return
            body = self.rfile.read(length) if length > 0 else b""
            if self.command == "POST":
                content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
                if content_type and content_type != "application/json":
                    resp = _json(
                        {
                            "error": (
                                f"unsupported Content-Type: {content_type} — "
                                "use application/json"
                            )
                        },
                        status=415,
                    )
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(resp.body)
                    return
            resp = app.handle(self.command, self.path, body=body)
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp.body)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    settings: Settings | None = None,
    app: WebApp | None = None,
) -> None:
    """Block and serve the workstation UI."""
    from http.server import ThreadingHTTPServer

    web_app = app or WebApp.from_settings(settings)
    handler = make_handler_class(web_app)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"ReproAgent workstation: http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def start_background_server(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    settings: Settings | None = None,
    app: WebApp | None = None,
) -> tuple[Any, str, WebApp]:
    """Start server in a daemon thread; return (httpd, base_url, app). Port 0 = ephemeral."""
    from http.server import ThreadingHTTPServer

    web_app = app or WebApp.from_settings(settings)
    handler = make_handler_class(web_app)
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="reproagent-web")
    thread.start()
    bound_host, bound_port = httpd.server_address[:2]
    base = f"http://{bound_host}:{bound_port}"
    return httpd, base, web_app
