#!/usr/bin/env python3
"""Batch driver: real CLI only; score full_no_fallback_success (>98% goal).

full_no_fallback_success requires:
  exit 0, status==passed, no soft_pass, no formula_fallback, no universe_fallback,
  every factor status in {passed, converged} without soft_pass, healthy metrics.
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
            name = p.name.lower()
            if "reading_plan" in name or p.parts[-2] in {"tmp", "scripts"}:
                continue
            key = p.resolve().as_posix()
            if key in seen:
                continue
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

    picked = md_first[:n]
    if len(picked) < n:
        picked.extend(pdf_second[: n - len(picked)])
    return picked[:n]


def _extract_json_blob(stdout: str) -> dict | None:
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("{") and ln.endswith("}"):
            try:
                return json.loads(ln)
            except json.JSONDecodeError:
                continue
    matches = list(re.finditer(r"\{[\s\S]*\}", stdout))
    for m in reversed(matches):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def _score_full_no_fallback(exit_code: int, blob: dict | None, log: str) -> dict:
    """Score one run under the strict no-fallback definition."""
    status = (blob or {}).get("status", "hard_fail")
    factors = (blob or {}).get("factors") or []
    obs = (blob or {}).get("observability") or {}

    soft_from_obs = bool(obs.get("soft_pass"))
    formula_fb = bool(obs.get("formula_fallback"))
    universe_fb = bool(obs.get("universe_fallback"))

    # log-level detectors (defense in depth)
    if re.search(r"falling back to close|Unparseable formula.*falling back", log, re.I):
        formula_fb = True
    if re.search(
        r"Unrecognized ricequant universe|retry CSI300|falling back to CSI300",
        log,
        re.I,
    ):
        universe_fb = True

    soft_factors = 0
    hard_ok = 0
    bad_factor = 0
    zero_metric = 0
    for f in factors:
        st = f.get("status")
        soft = bool(f.get("soft_pass")) or str(f.get("reflection_status") or "").startswith(
            "soft_pass"
        )
        if soft:
            soft_factors += 1
            soft_from_obs = True
        if st in {"passed", "converged"} and not soft:
            hard_ok += 1
            m = f.get("metrics") or {}
            vals = [
                abs(float(m.get(k) or 0))
                for k in ("ic_mean", "sharpe_ratio", "max_drawdown", "long_short_annual_return")
            ]
            if m and max(vals) < 1e-12:
                zero_metric += 1
        elif st not in {"passed", "converged"}:
            bad_factor += 1

    full = (
        exit_code == 0
        and status == "passed"
        and not soft_from_obs
        and soft_factors == 0
        and not formula_fb
        and not universe_fb
        and bad_factor == 0
        and zero_metric == 0
        and hard_ok >= 1
        and len(factors) >= 1
    )

    mode = "full_no_fallback_success"
    if full:
        mode = "full_no_fallback_success"
    elif exit_code != 0 or status == "hard_fail":
        mode = "hard_fail"
    elif formula_fb:
        mode = "formula_fallback"
    elif universe_fb:
        mode = "universe_fallback"
    elif soft_from_obs or soft_factors:
        mode = "soft_pass"
    elif status == "partial" or bad_factor:
        mode = "partial_or_factor_fail"
    elif status == "review_enqueued":
        mode = "review_enqueued"
    elif status == "error":
        mode = "error"
    elif status == "no_factors":
        mode = "no_factors"
    else:
        mode = f"other:{status}"

    return {
        "full_no_fallback_success": full,
        "failure_mode": mode if not full else None,
        "soft_pass": soft_from_obs or soft_factors > 0,
        "formula_fallback": formula_fb,
        "universe_fallback": universe_fb,
        "hard_ok_factors": hard_ok,
        "soft_factors": soft_factors,
        "bad_factors": bad_factor,
        "zero_metric_passed": zero_metric,
        "status": status,
        "factor_count": len(factors),
        "factor_statuses": [f.get("status") for f in factors],
        "observability": obs,
    }


def run_one(path: Path, timeout: int, env: dict[str, str]) -> dict:
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
        stdout, stderr = "", str(exc)

    blob = _extract_json_blob(stdout)
    log = stdout + "\n" + stderr
    scored = _score_full_no_fallback(exit_code, blob, log)
    return {
        "path": str(path),
        "name": path.name,
        "exit_code": exit_code,
        "seconds": round(time.time() - t0, 2),
        "error_snippet": (stderr or stdout)[-400:].replace("\n", " ")
        if not scored["full_no_fallback_success"]
        else "",
        **scored,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch reproagent full_no_fallback scoring")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--corpus", type=Path, default=CORPUS_DEFAULT)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--data-source", default=os.environ.get("DATA_SOURCE", "ricequant"))
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
    if not articles:
        print("error: no articles selected", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["DATA_SOURCE"] = args.data_source
    env["LOCAL_DATA_PATH"] = args.local_data
    # 严格评分：关闭公式→close 静默回退（同时禁用 soft_pass）
    env["ALLOW_FORMULA_FALLBACK"] = "false"
    env["APP_ENV"] = env.get("APP_ENV") or "prod"
    # prod 需要 mock 关；有 LLM key 时用真实提取
    env.setdefault("ALLOW_MOCK_LLM", "false")

    results: list[dict] = []
    jsonl_path.write_text("", encoding="utf-8")
    print(
        f"Running {len(articles)} articles; data_source={args.data_source}; "
        f"ALLOW_FORMULA_FALLBACK=false",
        flush=True,
    )
    for i, path in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] {path.name[:60]}…", flush=True)
        row = run_one(path, timeout=args.timeout, env=env)
        results.append(row)
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"  -> full={row['full_no_fallback_success']} status={row['status']} "
            f"mode={row.get('failure_mode')} soft={row['soft_pass']} "
            f"form_fb={row['formula_fallback']} univ_fb={row['universe_fallback']} "
            f"{row['seconds']}s",
            flush=True,
        )

    n = len(results)
    n_full = sum(1 for r in results if r["full_no_fallback_success"])
    rate = (n_full / n) if n else 0.0
    modes = Counter(r.get("failure_mode") or "full_no_fallback_success" for r in results)
    summary = {
        "n": n,
        "n_full_no_fallback_success": n_full,
        "full_no_fallback_success_rate": rate,
        "mode_counts": dict(modes),
        "data_source": args.data_source,
        "local_data_path": args.local_data,
        "corpus": str(args.corpus),
        "allow_formula_fallback": False,
        "success_definition": (
            "exit0 & status=passed & no soft_pass & no formula_fallback & "
            "no universe_fallback & all factors hard passed/converged & non-degenerate metrics"
        ),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if n >= 50 and rate > 0.98 else 1


if __name__ == "__main__":
    raise SystemExit(main())
