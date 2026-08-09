#!/usr/bin/env python3
"""Batch driver: real CLI; honest full_no_fallback_success scoring.

full_no_fallback_success requires ALL of:
  - exit 0, status == passed (not partial)
  - observability.formula_fallback == False
  - observability.formula_proxy == False
  - observability.universe_fallback == False
  - observability.soft_pass == False
  - every factor status in {passed, converged}, none soft_pass
  - non-degenerate metrics on success factors
  - no log markers of falling-back-to-close / silent CSI300 after unrecognized universe
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
            (md_first if suf == ".md" else pdf_second).append(p)
            if len(md_first) + len(pdf_second) >= n * 3:
                break
        if len(md_first) >= n:
            break
    picked = md_first[:n]
    if len(picked) < n:
        picked.extend(pdf_second[: n - len(picked)])
    return picked[:n]


def _extract_json_blob(stdout: str) -> dict | None:
    for ln in reversed([ln.strip() for ln in stdout.splitlines() if ln.strip()]):
        if ln.startswith("{") and ln.endswith("}"):
            try:
                return json.loads(ln)
            except json.JSONDecodeError:
                continue
    return None


def _score_full_no_fallback(exit_code: int, blob: dict | None, log: str) -> dict:
    status = (blob or {}).get("status", "hard_fail")
    factors = (blob or {}).get("factors") or []
    obs = (blob or {}).get("observability") or {}

    formula_fb = bool(obs.get("formula_fallback"))
    formula_proxy = bool(obs.get("formula_proxy"))
    universe_fb = bool(obs.get("universe_fallback"))
    soft = bool(obs.get("soft_pass"))

    # Only match real log events — not JSON keys like "formula_proxy": false
    if re.search(
        r"falling back to close|Unparseable formula.*falling back to close",
        log,
        re.I,
    ):
        formula_fb = True
    if re.search(
        r"Unrecognized ricequant universe .*falling back|get_price failed.*retry CSI300",
        log,
        re.I,
    ):
        universe_fb = True
    if re.search(
        r"mark_formula_proxy|formula proxy applied|extract_proxy:|compute_proxy:|unhealthy_retry_proxy:",
        log,
        re.I,
    ):
        formula_proxy = True
        formula_fb = True

    soft_factors = 0
    hard_ok = 0
    bad = 0
    zero_m = 0
    ics: list[float] = []
    for f in factors:
        st = f.get("status")
        is_soft = bool(f.get("soft_pass")) or str(f.get("reflection_status") or "").startswith(
            "soft_pass"
        )
        if is_soft:
            soft_factors += 1
            soft = True
        if st in {"passed", "converged"} and not is_soft:
            hard_ok += 1
            m = f.get("metrics") or {}
            ic = m.get("ic_mean")
            if ic is not None:
                ics.append(float(ic))
            vals = [
                abs(float(m.get(k) or 0))
                for k in ("ic_mean", "sharpe_ratio", "max_drawdown", "long_short_annual_return")
            ]
            if m and max(vals) < 1e-12:
                zero_m += 1
        elif st not in {"passed", "converged"}:
            bad += 1

    # 多因子相同 ic 到 1e-12 且>1 个 → 可疑同一代理式（记录但不单独否决，依赖 proxy 旗标）
    identical_ic_theater = len(ics) >= 3 and len({round(x, 12) for x in ics}) == 1

    full = (
        exit_code == 0
        and status == "passed"
        and not soft
        and soft_factors == 0
        and not formula_fb
        and not formula_proxy
        and not universe_fb
        and bad == 0
        and zero_m == 0
        and hard_ok >= 1
        and len(factors) >= 1
    )

    if full:
        mode = None
    elif formula_proxy or formula_fb:
        mode = "formula_proxy_or_fallback"
    elif universe_fb:
        mode = "universe_fallback"
    elif soft or soft_factors:
        mode = "soft_pass"
    elif status == "partial" or bad:
        mode = "partial_or_factor_fail"
    elif status == "no_factors":
        mode = "no_factors"
    elif status == "review_enqueued":
        mode = "review_enqueued"
    elif exit_code != 0:
        mode = "hard_fail"
    else:
        mode = f"other:{status}"

    return {
        "full_no_fallback_success": full,
        "failure_mode": mode,
        "soft_pass": soft,
        "formula_fallback": formula_fb,
        "formula_proxy": formula_proxy,
        "universe_fallback": universe_fb,
        "identical_ic_theater_suspect": identical_ic_theater,
        "hard_ok_factors": hard_ok,
        "bad_factors": bad,
        "zero_metric_passed": zero_m,
        "status": status,
        "factor_count": len(factors),
        "factor_statuses": [f.get("status") for f in factors],
        "ics": ics,
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
        stdout, stderr = proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = -9
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        exit_code, stdout, stderr = -1, "", str(exc)

    blob = _extract_json_blob(stdout)
    scored = _score_full_no_fallback(exit_code, blob, stdout + "\n" + stderr)
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--corpus", type=Path, default=CORPUS_DEFAULT)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--data-source", default="ricequant")
    ap.add_argument("--local-data", default="/home/wh/Documents/Data")
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "batch_results.jsonl"
    summary_path = out_dir / "batch_summary.json"

    articles = select_articles(args.corpus, args.n)
    if not articles:
        print("error: no articles", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["DATA_SOURCE"] = args.data_source
    env["LOCAL_DATA_PATH"] = args.local_data
    env["ALLOW_FORMULA_FALLBACK"] = "false"
    env["APP_ENV"] = "prod"
    env["ALLOW_MOCK_LLM"] = "false"

    results: list[dict] = []
    jsonl_path.write_text("", encoding="utf-8")
    print(
        f"Running {len(articles)}; DATA_SOURCE={args.data_source}; "
        f"ALLOW_FORMULA_FALLBACK=false (honest no-proxy scoring)",
        flush=True,
    )
    for i, path in enumerate(articles, 1):
        print(f"[{i}/{len(articles)}] {path.name[:55]}…", flush=True)
        row = run_one(path, args.timeout, env)
        results.append(row)
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"  -> full={row['full_no_fallback_success']} status={row['status']} "
            f"mode={row['failure_mode']} proxy={row['formula_proxy']} "
            f"univ_fb={row['universe_fallback']} {row['seconds']}s",
            flush=True,
        )

    n = len(results)
    n_full = sum(1 for r in results if r["full_no_fallback_success"])
    rate = n_full / n if n else 0.0
    modes = Counter(r["failure_mode"] or "full_no_fallback_success" for r in results)
    summary = {
        "n": n,
        "n_full_no_fallback_success": n_full,
        "full_no_fallback_success_rate": rate,
        "mode_counts": dict(modes),
        "data_source": args.data_source,
        "local_data_path": args.local_data,
        "corpus": str(args.corpus),
        "allow_formula_fallback": False,
        "allow_formula_proxy": False,
        "success_definition": (
            "exit0 & status=passed & no soft_pass & no formula_fallback "
            "& no formula_proxy & no universe_fallback & all factors hard-pass "
            "& non-degenerate metrics"
        ),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if n >= 50 and rate > 0.98 else 1


if __name__ == "__main__":
    raise SystemExit(main())
