from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
import numpy as np
import pandas as pd
from .factor_db import FactorDB


@dataclass
class FactorResult:
    name: str; ic: float; rank_ic: float; pnl: pd.Series; rank: int = 0


class PolarsEngine:
    def calc(self, data: pd.DataFrame, formula: str) -> pd.Series:
        return data[formula].astype(float) if formula in data.columns else pd.Series(0.0, index=data.index)


class RiceQuantEval:
    def evaluate(self, factor: pd.Series, price: pd.Series) -> Dict[str, float]:
        ret = price.pct_change()
        aligned = pd.concat([factor.rename("f"), ret.rename("r")], axis=1).dropna()
        if len(aligned) < 2: return {"ic": 0.0, "rank_ic": 0.0}
        return {"ic": float(aligned["f"].corr(aligned["r"])),
                "rank_ic": float(aligned["f"].rank().corr(aligned["r"].rank()))}


class StrategyBacktester:
    def run(self, factor: pd.Series, price: pd.Series, n_groups: int = 5) -> pd.Series:
        ret = price.pct_change().fillna(0)
        groups = pd.qcut(factor.rank(method="first"), n_groups, labels=False, duplicates="drop") + 1
        signal = pd.Series(0.0, index=price.index)
        signal[groups == groups.max()] = 1.0; signal[groups == groups.min()] = -1.0
        return (signal * ret).fillna(0)


class DeviationAnalyzer:
    def analyze(self, pnl: pd.Series, bench: pd.Series) -> Dict[str, float]:
        diff = (pd.concat([pnl.rename("p"), bench.rename("b")], axis=1).fillna(0)["p"]
                - pd.concat([pnl.rename("p"), bench.rename("b")], axis=1).fillna(0)["b"])
        return {"mean_dev": float(diff.mean()), "std_dev": float(diff.std()),
                "tracking_error": float(diff.std() * np.sqrt(252))}


class FactorDiscoverer:
    def __init__(self, build_evaluator: bool = False, train_ratio: float = 0.7):
        self.build_evaluator_enabled = build_evaluator
        self.train_ratio = train_ratio
        self.engine = PolarsEngine()
        self.eval_engine = RiceQuantEval()
        self.backtester = StrategyBacktester()
        self.deviation = DeviationAnalyzer()

    def _prepare(self, data: pd.DataFrame):
        n = int(len(data) * self.train_ratio)
        return data.iloc[:n].copy(), data.iloc[n:].copy()

    def discover(self, formulas: List[str], data: pd.DataFrame, price_col: str = "close") -> List[FactorResult]:
        train, _ = self._prepare(data)
        results = []
        for fml in formulas:
            factor = self.engine.calc(train, fml)
            stats = self.eval_engine.evaluate(factor, train[price_col])
            results.append(FactorResult(name=fml, ic=stats["ic"], rank_ic=stats["rank_ic"],
                                        pnl=self.backtester.run(factor, train[price_col])))
        results.sort(key=lambda r: r.rank_ic, reverse=True)
        for i, r in enumerate(results, 1): r.rank = i
        return results

    def deviation_report(self, pnl: pd.Series, bench: pd.Series) -> Dict[str, float]:
        return self.deviation.analyze(pnl, bench)


@dataclass
class DeviationCase:
    case_id: str; is_reverse_pv: bool; category: str
    retry_count: int = 0; params: Dict[str, Any] = field(default_factory=dict)


class FactorErrorManager:
    def __init__(self, max_layout_retries: int = 2):
        self.max_layout_retries = max_layout_retries
        self.tickets: List[DeviationCase] = []

    def prepare_params(self, case: DeviationCase) -> Dict[str, Any]:
        if case.category == "entity_merge": return {"mode": "merge", "src": "法人库", "dst": "工程线"}
        if case.category == "layout_reflection": n = self.max_layout_retries; return {"mode": "layout", "max_retries": n, "limit": n + 2}
        return {"mode": "unknown"}

    def submit(self, case: DeviationCase) -> DeviationCase:
        case.params = self.prepare_params(case); self.tickets.append(case); return case


class DeviationController:
    def __init__(self, max_layout_retries: int = 2):
        self.manager = FactorErrorManager(max_layout_retries)
        self.log: List[Dict[str, Any]] = []

    def handle(self, case_id: str, is_reverse_pv: bool, category: str, retry_count: int = 0) -> Dict[str, Any]:
        if not is_reverse_pv:
            entry = {"case_id": case_id, "action": "skip", "reason": "not_reverse_pv"}; self.log.append(entry); return entry
        case = DeviationCase(case_id=case_id, is_reverse_pv=True, category=category, retry_count=retry_count)
        if category == "entity_merge":
            ticket = self.manager.submit(case)
        elif category == "layout_reflection":
            if retry_count > self.manager.max_layout_retries + 2:
                entry = {"case_id": case_id, "action": "drop", "reason": "exceed_N_plus_2"}; self.log.append(entry); return entry
            ticket = self.manager.submit(case)
        else:
            entry = {"case_id": case_id, "action": "error", "reason": f"unknown_category:{category}"}; self.log.append(entry); return entry
        entry = {"case_id": case_id, "action": "submit", "category": ticket.category, "params": ticket.params}
        self.log.append(entry); return entry


if __name__ == "__main__":
    np.random.seed(42); n = 500
    data = pd.DataFrame({"x1": np.random.randn(n), "x2": np.random.randn(n),
                         "x3": np.random.randn(n), "close": 100 + np.cumsum(np.random.randn(n) * 0.5)})
    db = FactorDB()
    fd = FactorDiscoverer(build_evaluator=False)
    factors = fd.discover(["x1", "x2", "x3"], data)
    for f in factors:
        pnl_list = f.pnl.fillna(0).tolist(); ic_arr = np.array(pnl_list)
        ic_std = float(ic_arr.std()) if len(ic_arr) > 1 else 0.0
        icir = f.ic / ic_std if ic_std > 0 else 0
        exp_cum = np.exp(np.cumsum(pnl_list))
        ann = float((exp_cum[-1] - 1) * 100)
        mdd = float((np.minimum.accumulate(exp_cum) / np.maximum.accumulate(exp_cum) - 1).min() * 100)
        win = float((np.array(pnl_list) > 0).mean() * 100)
        ic_data = (np.random.randn(n) * 0.03 + f.ic).clip(-0.35, 0.35).tolist()
        db.save_factor(f.name, f.rank, f.ic, f.rank_ic, ic_std, icir, ann, mdd, win, ic_data, pnl_list)
        print(f"  + {f.name} rank={f.rank} ic={f.ic:.4f} -> DB saved")
    ctrl = DeviationController(max_layout_retries=2)
    for cid, rev, cat, retry in [("C-001", True, "entity_merge", 0), ("C-002", True, "layout_reflection", 1), ("C-003", False, "entity_merge", 0)]:
        r = ctrl.handle(cid, rev, cat, retry); db.save_deviation(r.get("case_id", cid), r.get("action", "?"), r.get("category", ""), r.get("params", {}))
        print(f"  + {cid} -> {r['action']} -> DB saved")
    db.close(); print(f"\n  DB: {db.db_path}")
