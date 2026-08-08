#!/usr/bin/env python3
"""Batch driver: run real `reproagent text|reproduce` CLI on categorized articles.

Writes JSONL + summary under a scratch/output directory. Scoring matches the goal:
success iff exit_code==0 and status in {passed, partial}.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


CORPUS_DEFAULT = Path(
    "/home/wh/Documents/KnowledgeBase/Quant/WH/Articles/categorized"
)
SUCCESS_STATUSES = frozenset({"passed", "partial"})


def select_articles(corpus: Path, n: int, prefer_factor: bool = True) -> list[Path]:
    """Pick distinct articles, preferring factor_investing markdown of moderate size."""
    roots: list[Path] = []
    if prefer_factor:
        fi = corpus / "factor_investing"
        if fi.is_dir():
            roots.append(fi)
    roots.append(corpus)

    seen: set[str] = set()
    md_first: list[Path] = []
    pdf_second: list[Path] = []

    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            suf = p.suffix.lower()
            if suf not in {".md", ".pdf"}:
                continue
            # skip reading plans / tmp junk
            name = p.name.lower()
            if "reading_plan" in name or p.parts[-2] in {"tmp", "scripts"}:
                continue
            key = p.resolve().as_posix()
            if key in seen:
                continue
            # size filter: skip tiny stubs and huge books
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz < 1500 or sz > 400_000:
                continue
            seen.add(key)
            if suf == ".md":
                md_first.append(p)
            else:
                pdf_second.append(p)
            if len(md_first) + len(pdf_second) >= n * 3:
                break
        if len(md_first) >= n:
            break

    # Prefer MD (skip heavy PDF layout); fill with PDF if needed
    picked = md_first[:n]
    if len(picked) < n:
        picked.extend(pdf_second[: n - len(picked)])
    return picked[:n]


def _extract_json_blob(stdout: str) -> dict | None:
    """Last JSON object in CLI stdout (after 'text ok' / 'reproduce ok')."""
    # Prefer last line that is a full JSON object
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("{") and ln.endswith("}"):
            try:
                return json.loads(ln)
            except json.JSONDecodeError:
                continue
    # Fallback: greedy last {...}
    matches = list(re.finditer(r"\{[\s\S]*\}", stdout))
    for m in reversed(matches):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def run_one(path: Path, timeout: int, env: dict[str, str]) -> dict:
    """Invoke shipped CLI for one article."""
    t0 = time.time()
    if path.suffix.lower() == ".md":
        cmd = [
            "uv",
            "run",
            "reproagent",
            "text",
            "-f",
            str(path),
            "-t",
            path.stem[:80],
            "-b",
            "batch",
        ]
    else:
        cmd = ["uv", "run", "reproagent", "reproduce", str(path)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = -9
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        exit_code = -1
        stdout = ""
        stderr = str(exc)

    blob = _extract_json_blob(stdout)
    status = "hard_fail"
    if blob and isinstance(blob, dict) and "status" in blob:
        status = str(blob["status"])
    elif exit_code != 0:
        status = "hard_fail"

    success = exit_code == 0 and status in SUCCESS_STATUSES
    err_snip = (stderr or stdout or "")[-400:].replace("\n", " ")
    return {
        "path": str(path),
        "exit_code": exit_code,
        "status": status,
        "success": success,
        "seconds": round(time.time() - t0, 2),
        "error_snippet": err_snip if not success else "",
        "factor_count": (blob or {}).get("factor_count"),
        "summary": (blob or {}).get("summary"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch reproagent on categorized articles")
    ap.add_argument("--n", type=int, default=50, help="Number of articles")
    ap.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS_DEFAULT,
        help="Root of categorized articles",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Directory for batch_results.jsonl + batch_summary.json",
    )
    ap.add_argument("--timeout", type=int, default=240, help="Per-article timeout seconds")
    ap.add_argument(
        "--data-source",
        default=os.environ.get("DATA_SOURCE", "ricequant"),
        help="DATA_SOURCE env for child processes",
    )
    ap.add_argument(
        "--local-data",
        default=os.environ.get("LOCAL_DATA_PATH", "/home/wh/Documents/Data"),
    )
    args = ap.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "batch_results.jsonl"
    summary_path = out_dir / "batch_summary.json"

    articles = select_articles(args.corpus, args.n)
    if len(articles) < args.n:
        print(
            f"warn: only found {len(articles)} articles (requested {args.n})",
            file=sys.stderr,
        )
    if not articles:
        print("error: no articles selected", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["DATA_SOURCE"] = args.data_source
    env["LOCAL_DATA_PATH"] = args.local_data
    # Ensure ricequant extras usable; leave RQ_* from parent env

    results: list[dict] = []
    # Truncate jsonl for this run
    jsonl_path.write_text("", encoding="utf-8")

    print(f"Running {len(articles)} articles; data_source={args.data_source}", flush=True)
    for i, path in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] {path.name[:60]}…", flush=True)
        row = run_one(path, timeout=args.timeout, env=env)
        results.append(row)
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"  -> exit={row['exit_code']} status={row['status']} "
            f"success={row['success']} {row['seconds']}s",
            flush=True,
        )

    n = len(results)
    n_success = sum(1 for r in results if r["success"])
    rate = (n_success / n) if n else 0.0
    by_status = Counter(r["status"] for r in results)
    summary = {
        "n": n,
        "n_success": n_success,
        "success_rate": rate,
        "failure_counts_by_status": dict(by_status),
        "data_source": args.data_source,
        "local_data_path": args.local_data,
        "corpus": str(args.corpus),
        "success_definition": "exit_code==0 and status in {passed, partial}",
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if n >= 50 and rate > 0.95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
