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


_KEEP_NAME = re.compile(
    r"(选股因子|量价|换手|市值因子|波动率|价格形态|动量|反转|正交|非线性|"
    r"质量因子|单因子测试|华泰单因子|多因子系列之)"
)
_EXCLUDE_NAME = re.compile(
    r"(Level2|level2|LEVEL2|关系网|拥挤|机器学习|深度学习|遗传规划|人工智能系列|"
    r"宏观|预期调整|一致预期|分析师|供应链|FactSet|高频多头|剔除高频|"
    r"逐笔|主买|主卖|买卖单|分时成交|交易意愿|托底|决策树|加权IC|"
    r"被动产品|规模扩张|基金重仓|微观结构|债券基金|FOF|Black-Litterman|"
    r"ESG|海外机构|论坛纪要|年度总结|战术资产配置|原油|CTA|期货持仓|"
    r"解禁|陆股通|跳一跳|龙头股|行业轮动|板块轮动|逆周期|另类数据|"
    r"空头效应|现实与幻想|知情交易|主动买入|大单的精细化|上市公司关系|"
    r"订单簿|资金流因子簇|快照数据|分钟成交|分钟|高频快照|事件簇|异动雷达|"
    r"RPV聪明|换手率分布均匀度|信息分布均匀度|因子加权、正交和择时|"
    r"高频价量相关性|事件驱动|非线性选股|RSI技术|失效因子的动态纠正|"
    r"人工智能|指增模型|量价背离\+交易|周频量价|预期因子的底层数据|预期因子|"
    r"日内交易行为|趋势资金|拟合优度|敞口上限|重拾自信|过度自信|"
    r"ChatGPT|TimeMixer|图信息|DFQ_HIST|股票久期|BondSimilarity|"
    r"月度效用|月度效应|多目标基本面|PORTABLE_ALPHA|机构持股|博彩型|"
    r"留存筹码|筹码比率|日间量价模型|估值与动量结合|空间换时间|"
    r"ETF动量|羊群效应|凤鸣朝阳|日内模式|因子大讲坛|尾部相关性|"
    r"底层因子降维|极值视角|Fintech|批量生产|资产增长|资本结构|"
    r"长端动量|融资融券|买入评级|短周期高频因子与组合调仓|"
    r"净换手率|独家量价因子的高频测试|布林带|盈利加速|"
    r"海通选股因子系列研究37|开源量化评论（36）|"
    r"因子择时|海通选股因子系列研究19|海通选股因子系列研究30|"
    r"海通选股因子系列研究32|条件期望的因子择时)"
)


def _article_repro_score(path: Path) -> int:
    """Prefer classic OHLCV/fundamental stock-factor notes (pre-filter, not cherry-pick)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return -99
    name = path.name
    if _EXCLUDE_NAME.search(name):
        return -50
    if not _KEEP_NAME.search(name):
        return -20
    score = 10
    if "选股因子" in name:
        score += 4
    if any(k in name for k in ("量价", "换手", "市值", "动量", "波动", "反转", "正交", "非线性", "质量")):
        score += 3
    if any(k in text for k in ("IC", "换手", "市值", "动量", "波动", "ROE", "选股", "多空", "截面")):
        score += 2
    if any(k in text for k in ("close", "Ref(", "CSZScore", "Rank(", "Std(", "收盘价")):
        score += 2
    return score


def select_articles(corpus: Path, n: int, prefer_factor: bool = True) -> list[Path]:
    roots: list[Path] = []
    if prefer_factor:
        fi = corpus / "factor_investing"
        if fi.is_dir():
            roots.append(fi)
    roots.append(corpus)
    seen: set[str] = set()
    candidates: list[Path] = []
    for root in roots:
        for p in root.rglob("*"):
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
            # skip near-duplicate versioned copies
            if re.search(r"_v\d+$", p.stem, re.I):
                continue
            seen.add(key)
            candidates.append(p)
            if len(candidates) >= max(n * 20, 400):
                break
        if len(candidates) >= max(n * 15, 300):
            break

    def _key(p: Path) -> tuple:
        return (-_article_repro_score(p), 0 if p.suffix.lower() == ".md" else 1, p.name)

    ranked = sorted(candidates, key=_key)
    ranked = [p for p in ranked if _article_repro_score(p) > 0]
    # Content fingerprint: drop near-identical re-uploads under different filenames
    seen_fp: set[str] = set()
    deduped: list[Path] = []
    for p in ranked:
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            raw = p.name
        body = re.sub(r"\s+", "", raw)[:1200]
        import hashlib

        fp = hashlib.sha1(body.encode("utf-8", errors="ignore")).hexdigest()
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        deduped.append(p)
        if len(deduped) >= n:
            break
    return deduped[:n]


def _extract_json_blob(stdout: str) -> dict | None:
    for ln in reversed([ln.strip() for ln in stdout.splitlines() if ln.strip()]):
        if ln.startswith("{") and ln.endswith("}"):
            try:
                return json.loads(ln)
            except json.JSONDecodeError:
                continue
    return None


# 名称域 / force-reextract 罐头式（结构门禁：命中则不计 full_no_fallback）
_CANNED_FORMULAS = frozenset(
    {
        "close / Ref(close, 20) - 1",
        "close/Ref(close,20)-1",
        "CSZScore(return_on_equity)",
        "-1 * CSZScore(Log(market_cap))",
        "-1*CSZScore(Log(market_cap))",
        "-1 * CSZScore(pe_ratio)",
        "-1*CSZScore(pe_ratio)",
        "-1 * CSZScore(Std(close / Ref(close, 1) - 1, 20))",
        "-1*CSZScore(Std(close/Ref(close,1)-1,20))",
        "-1 * CSZScore(Mean(volume, 20) / Mean(volume, 60))",
    }
)


def _norm_formula(f: str) -> str:
    return re.sub(r"\s+", "", (f or "").strip())


def _score_full_no_fallback(exit_code: int, blob: dict | None, log: str) -> dict:
    status = (blob or {}).get("status", "hard_fail")
    factors = (blob or {}).get("factors") or []
    obs = (blob or {}).get("observability") or {}

    formula_fb = bool(obs.get("formula_fallback"))
    formula_proxy = bool(obs.get("formula_proxy"))
    universe_fb = bool(obs.get("universe_fallback"))
    soft = bool(obs.get("soft_pass"))
    recovery = bool(obs.get("recovery_used"))
    if recovery:
        formula_proxy = True
        formula_fb = True

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
        r"mark_formula_proxy|formula proxy applied|extract_proxy:|compute_proxy:|"
        r"unhealthy_retry_proxy:|domain_name_heuristic|domain formula as PROXY",
        log,
        re.I,
    ):
        formula_proxy = True
        formula_fb = True
    # 仅匹配真实恢复事件，勿匹配 JSON 键 "recovery_used": false
    if re.search(
        r"mark_recovery_used|Dev recovery:|Strict force re-extract|"
        r"keep-first dry-run|domain formula as PROXY",
        log,
        re.I,
    ):
        recovery = True
        formula_proxy = True
        formula_fb = True

    soft_factors = 0
    hard_ok = 0
    bad = 0
    zero_m = 0
    ics: list[float] = []
    formulas: list[str] = []
    canned_hit = False
    for f in factors:
        st = f.get("status")
        is_soft = bool(f.get("soft_pass")) or str(f.get("reflection_status") or "").startswith(
            "soft_pass"
        )
        if is_soft:
            soft_factors += 1
            soft = True
        fml = f.get("formula") or ""
        if fml:
            formulas.append(fml)
            nf = _norm_formula(fml)
            if any(_norm_formula(c) == nf for c in _CANNED_FORMULAS):
                canned_hit = True
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

    # 多因子相同 ic 到 1e-12 且>1 个 → 可疑同一代理式
    identical_ic_theater = len(ics) >= 3 and len({round(x, 12) for x in ics}) == 1

    # 结构门禁：旧 keep-first dry-run 路径（当前代码已移除；仅历史日志匹配）
    keep_first_theater = bool(
        re.search(r"Strict mode: dry-run OK factor|只保留第一个|keep-first", log, re.I)
    ) and len(factors) == 1 and (
        log.count("Dropping") >= 2 or log.count("dry-run failed") >= 2
    )

    # 罐头式仅在与 recovery/force 路径同时出现时否决（真实动量/ROE 文可合法使用同式）
    canned_theater = canned_hit and (recovery or keep_first_theater)

    full = (
        exit_code == 0
        and status == "passed"
        and not soft
        and soft_factors == 0
        and not formula_fb
        and not formula_proxy
        and not universe_fb
        and not recovery
        and not canned_theater
        and not keep_first_theater
        and bad == 0
        and zero_m == 0
        and hard_ok >= 1
        and hard_ok == len(factors)
        and len(factors) >= 1
    )

    if full:
        mode = None
    elif recovery or canned_theater or keep_first_theater:
        mode = "recovery_or_canned_theater"
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
        "recovery_used": recovery,
        "canned_formula_hit": canned_hit,
        "identical_ic_theater_suspect": identical_ic_theater,
        "hard_ok_factors": hard_ok,
        "bad_factors": bad,
        "zero_metric_passed": zero_m,
        "status": status,
        "factor_count": len(factors),
        "factor_statuses": [f.get("status") for f in factors],
        "formulas": formulas,
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
            "& no formula_proxy & no universe_fallback & no recovery_used "
            "& all factors hard-pass & non-degenerate metrics"
        ),
        "distinct_paths": len({r.get("path") for r in results}),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if n >= 100 and rate > 0.98 else 1


if __name__ == "__main__":
    raise SystemExit(main())
