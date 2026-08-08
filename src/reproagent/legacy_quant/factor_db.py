import json, sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any

_DB_PATH = Path(__file__).parent / "factor_library.db"


class FactorDB:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DB_PATH
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS factors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            rank INTEGER, ic_mean REAL, rank_ic REAL, ic_std REAL,
            icir REAL, ann_return REAL, max_drawdown REAL, win_rate REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS factor_ts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, factor_id INTEGER NOT NULL,
            date_idx INTEGER NOT NULL, ic_value REAL, excess_value REAL,
            FOREIGN KEY (factor_id) REFERENCES factors(id)
        );
        CREATE TABLE IF NOT EXISTS deviation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL,
            action TEXT, category TEXT, params TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        self.conn.commit()

    def save_factor(
        self,
        name: str,
        rank: int,
        ic_mean: float,
        rank_ic: float,
        ic_std: float,
        icir: float,
        ann_return: float,
        max_drawdown: float,
        win_rate: float,
        ic_series: List[float],
        pnl_series: List[float],
    ) -> int:
        cur = self.conn.execute(
            "INSERT OR REPLACE INTO factors (name,rank,ic_mean,rank_ic,ic_std,icir,ann_return,max_drawdown,win_rate) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (name, rank, ic_mean, rank_ic, ic_std, icir, ann_return, max_drawdown, win_rate),
        )
        fid = cur.lastrowid
        if fid is None:
            row = self.conn.execute("SELECT id FROM factors WHERE name=?", (name,)).fetchone()
            fid = row["id"]
            self.conn.execute("DELETE FROM factor_ts WHERE factor_id=?", (fid,))
        excess = 100.0
        for i, (ic, pnl) in enumerate(zip(ic_series, pnl_series)):
            excess = round(excess * (1 + pnl), 6)
            self.conn.execute(
                "INSERT INTO factor_ts (factor_id,date_idx,ic_value,excess_value) VALUES (?,?,?,?)",
                (fid, i, ic, excess),
            )
        self.conn.commit()
        return fid

    def get_factors(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM factors ORDER BY rank").fetchall()
        return [dict(r) for r in rows]

    def get_factor_ts(self, factor_id: int) -> tuple:
        rows = self.conn.execute(
            "SELECT ic_value,excess_value FROM factor_ts WHERE factor_id=? ORDER BY date_idx",
            (factor_id,),
        ).fetchall()
        if not rows:
            return [], []
        return [r["ic_value"] for r in rows], [r["excess_value"] for r in rows]

    def save_deviation(self, case_id: str, action: str, category: str, params: dict):
        self.conn.execute(
            "INSERT INTO deviation_logs (case_id,action,category,params) VALUES (?,?,?,?)",
            (case_id, action, category, json.dumps(params, ensure_ascii=False)),
        )
        self.conn.commit()

    def get_deviation_logs(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM deviation_logs ORDER BY id").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["params"] = json.loads(d["params"]) if isinstance(d["params"], str) else d["params"]
            result.append(d)
        return result

    def seed_demo(self):
        import numpy as np

        np.random.seed(20260715)
        for i, name in enumerate(
            [
                "动量因子",
                "价值因子",
                "质量因子",
                "成长因子",
                "低波因子",
                "规模因子",
                "红利因子",
                "情绪因子",
                "技术因子",
                "流动性因子",
                "盈利因子",
                "杠杆因子",
            ]
        ):
            rng = np.random.default_rng(i * 7)
            n = 252
            ic = rng.uniform(-0.08, 0.12) + rng.uniform(0.02, 0.06) * rng.normal(size=n)
            ic = np.clip(ic, -0.35, 0.35).tolist()
            dr = np.array(ic) * 0.15 + rng.normal(0, 0.005, n)
            s = float(np.mean(ic))
            st = float(np.std(ic))
            cum = np.exp(np.cumsum(dr))
            running_max = np.maximum.accumulate(cum)
            mdd = float(((cum - running_max) / running_max).min() * 100)
            self.save_factor(
                name,
                i + 1,
                s,
                float(np.corrcoef(ic, np.argsort(dr))[0, 1]) if len(ic) > 1 else 0,
                st,
                s / st if st > 0 else 0,
                round((np.exp(np.cumsum(dr))[-1] - 1) * 100, 2),
                round(mdd, 2),
                round(float((dr > 0).mean() * 100), 2),
                ic,
                dr.tolist(),
            )
        self.save_deviation(
            "C-001", "submit", "entity_merge", {"mode": "merge", "src": "法人库", "dst": "工程线"}
        )
        self.save_deviation(
            "C-002", "submit", "layout_reflection", {"mode": "layout", "max_retries": 2, "limit": 4}
        )
        self.save_deviation("C-003", "skip", "", {"reason": "not_reverse_pv"})

    def close(self):
        self.conn.close()
