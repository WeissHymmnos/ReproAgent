"""量价 / 基本面数据加载。"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from reproagent.exceptions import ConfigurationError, ReproductionError
from reproagent.settings import Settings

logger = logging.getLogger(__name__)

# 转债 universe 别名（大小写不敏感）
_CB_UNIVERSE_ALIASES = frozenset(
    {
        "cb",
        "convertible",
        "convertible_bond",
        "convertible_bonds",
        "全转债",
        "转债",
        "可转债",
    }
)

# 命名股票池 → 米筐指数代码（全 A / all 用沪深 300 成分作可算代理，避免拉全市场）
_NAMED_UNIVERSE_INDEX: dict[str, str] = {
    "all": "000300.XSHG",
    "csi300": "000300.XSHG",
    "hs300": "000300.XSHG",
    "沪深300": "000300.XSHG",
    "csi500": "000905.XSHG",
    "zz500": "000905.XSHG",
    "中证500": "000905.XSHG",
    "csi1000": "000852.XSHG",
    "中证1000": "000852.XSHG",
    "全a股": "000300.XSHG",
    "全a": "000300.XSHG",
    "a股": "000300.XSHG",
    "全市场": "000300.XSHG",
}

# 进程内缓存：避免同一进程内重复拉同一指数面板
_RQ_PRICE_CACHE: dict[tuple[str, str, str], pl.DataFrame] = {}
_RQ_INITED = False
# 磁盘缓存目录（跨 CLI 子进程复用）
_RQ_DISK_CACHE_DIR = Path.home() / ".reproagent" / "cache" / "ricequant_prices"


def is_cb_universe(universe: str | list[str]) -> bool:
    """判断是否为转债股票池（非显式代码列表）。"""
    if isinstance(universe, list):
        return False
    u = (universe or "").strip()
    if not u:
        return False
    if u.lower() in _CB_UNIVERSE_ALIASES:
        return True
    return "转债" in u


def _normalize_rq_order_book_id(code: str) -> str:
    """把常见 A 股代码写成米筐 order_book_id。"""
    c = (code or "").strip()
    if not c:
        return c
    # 已是米筐格式
    if c.endswith((".XSHE", ".XSHG", ".XSHG", ".XBSE")):
        return c
    # 000001.SZ / 600000.SH
    m = re.match(r"^(\d{6})\.(SZ|SH|BJ)$", c, re.I)
    if m:
        num, exch = m.group(1), m.group(2).upper()
        if exch == "SZ":
            return f"{num}.XSHE"
        if exch == "SH":
            return f"{num}.XSHG"
        return f"{num}.XBSE"
    # 纯 6 位
    if re.fullmatch(r"\d{6}", c):
        if c.startswith(("5", "6", "9")):
            return f"{c}.XSHG"
        return f"{c}.XSHE"
    return c


class DataLoader:
    """从 ricequant / tushare / local 加载为 Polars DataFrame。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _ensure_rqdatac_init(self) -> Any:
        """初始化 rqdatac（token 或 user/pass）；进程内只做一次。"""
        global _RQ_INITED
        try:
            import rqdatac
        except ImportError as e:
            raise ConfigurationError(
                "rqdatac is not installed. Please install it to use ricequant data source."
            ) from e

        if _RQ_INITED:
            return rqdatac

        token = ""
        if self.settings.ricequant_token is not None:
            token = self.settings.ricequant_token.get_secret_value().strip()
        user = ""
        if self.settings.rq_user is not None:
            user = self.settings.rq_user.get_secret_value().strip()
        password = ""
        if self.settings.rq_pass is not None:
            password = self.settings.rq_pass.get_secret_value().strip()

        try:
            if token:
                # 与 aiminer / 官方 license 连接方式一致
                rqdatac.init(
                    uri=f"tcp://license:{token}@rqdatad-pro.ricequant.com:16011"
                )
            elif user and password:
                rqdatac.init(user, password)
            else:
                # 尝试环境默认（部分环境已 export）
                rqdatac.init()
            _RQ_INITED = True
        except Exception as e:
            raise ConfigurationError(
                "Failed to initialize rqdatac. Set RQ_TOKEN or RQ_USER+RQ_PASS "
                f"(from aiminer ricequant account). Underlying error: {e}"
            ) from e
        return rqdatac

    def _resolve_ricequant_instruments(
        self, universe: str | list[str], as_of: date
    ) -> list[str]:
        """将命名股票池 / 中文别名解析为米筐 order_book_id 列表。"""
        rqdatac = self._ensure_rqdatac_init()

        if isinstance(universe, list):
            codes = [_normalize_rq_order_book_id(str(x)) for x in universe if str(x).strip()]
            if not codes:
                raise ReproductionError("Empty instrument list for ricequant universe")
            return codes

        raw = (universe or "").strip() or "csi300"
        key = raw.lower().replace(" ", "")

        # 转债：取可转债列表（截断以免过大）
        if is_cb_universe(raw):
            try:
                inst = rqdatac.all_instruments(type="Convertible")
                if inst is not None and len(inst) > 0:
                    col = "order_book_id" if "order_book_id" in inst.columns else inst.columns[0]
                    codes = [str(x) for x in inst[col].tolist()[:400]]
                    if codes:
                        return codes
            except Exception as exc:  # noqa: BLE001
                raise ReproductionError(
                    f"Convertible universe resolve failed for {raw!r}: {exc}"
                ) from exc
            raise ReproductionError(f"Empty convertible instrument list for universe {raw!r}")

        # 命名指数 / 全 A（显式映射表；不是失败后静默代理）
        index_id = _NAMED_UNIVERSE_INDEX.get(key)
        if index_id is None:
            if "1000" in key:
                index_id = "000852.XSHG"
            elif "500" in key:
                index_id = "000905.XSHG"
            elif "300" in key or "沪深300" in raw:
                index_id = "000300.XSHG"
            elif key in {"all", "全市场"} or "全a" in key or "a股" in key:
                index_id = "000300.XSHG"

        if index_id is not None:
            try:
                comps = rqdatac.index_components(index_id, date=as_of)
                if comps:
                    return list(comps)
            except Exception as exc:  # noqa: BLE001
                logger.warning("index_components(%s) failed: %s; trying latest", index_id, exc)
                try:
                    comps = rqdatac.index_components(index_id)
                    if comps:
                        return list(comps)
                except Exception as exc2:  # noqa: BLE001
                    raise ReproductionError(
                        f"Cannot resolve ricequant universe {raw!r}: {exc2}"
                    ) from exc2
            raise ReproductionError(f"Empty index components for universe {raw!r} ({index_id})")

        # 单个合法代码
        code = _normalize_rq_order_book_id(raw)
        if re.fullmatch(r"\d{6}\.(XSHE|XSHG|XBSE)", code):
            return [code]

        # 未知描述性股票池：硬失败（不再静默 CSI300）
        from reproagent.reproducer.run_flags import mark_universe_fallback

        mark_universe_fallback(f"unrecognized_universe:{raw}")
        raise ReproductionError(
            f"Unrecognized ricequant universe {raw!r}; "
            "normalize at extract to csi300/csi500/csi1000/全转债"
        )

    def load_price_data(
        self,
        universe: str | list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """日频量价：trade_date, ts_code, open, high, low, close, volume, amount。

        转债 universe（全转债/cb）在 local 模式下优先读取 ``cb_prices.parquet``。
        """
        if self.settings.data_source == "local":
            return self._load_local_price(universe, start, end)
        elif self.settings.data_source == "ricequant":
            return self._load_ricequant_price(universe, start, end)
        elif self.settings.data_source == "qlib":
            return self._load_qlib_price(universe, start, end)
        elif self.settings.data_source == "tushare":
            return self._load_tushare_price(universe, start, end)
        else:
            raise ConfigurationError(f"Unknown data source: {self.settings.data_source}")

    def load_fundamental_data(
        self,
        fields: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """基本面字段，如 roe_ttm, pe_ttm, turnover_rate, market_cap。

        Returns
        -------
        pl.DataFrame with columns: trade_date, ts_code, + requested fields.
        """
        if self.settings.data_source == "local":
            return self._load_local_fundamental(fields, start, end)
        elif self.settings.data_source == "ricequant":
            return self._load_ricequant_fundamental(fields, start, end)
        elif self.settings.data_source == "tushare":
            return self._load_tushare_fundamental(fields, start, end)
        elif self.settings.data_source == "qlib":
            return self._load_qlib_fundamental(fields, start, end)
        else:
            raise ConfigurationError(
                f"Fundamental data not configured for {self.settings.data_source}"
            )

    def _resolve_local_data_path(self) -> Path:
        data_path = self.settings.local_data_path
        if data_path is None:
            data_path = Path("tests/fixtures/test_data")
            if not data_path.exists():
                raise ConfigurationError(
                    "local_data_path is not set and tests/fixtures/test_data does not exist."
                )
        return Path(data_path)

    def _load_local_price(self, universe: str | list[str], start: date, end: date) -> pl.DataFrame:
        data_path = self._resolve_local_data_path()

        # 转债池优先 cb_prices.parquet
        prefer_cb = is_cb_universe(universe)
        candidates: list[Path] = []
        if prefer_cb:
            candidates.append(data_path / "cb_prices.parquet")
            candidates.append(data_path / "cb_prices.csv")
        candidates.extend(
            [
                data_path / "prices.parquet",
                data_path / "prices.csv",
            ]
        )
        if not prefer_cb:
            # 非转债也允许在无股票文件时回退到转债 fixture（仅测试便利）
            candidates.append(data_path / "cb_prices.parquet")

        df: pl.DataFrame | None = None
        for path in candidates:
            if not path.exists():
                continue
            if path.suffix == ".parquet":
                df = pl.read_parquet(path)
            else:
                df = pl.read_csv(path)
            break

        if df is None:
            raise ConfigurationError(
                f"No prices/cb_prices parquet or csv found in {data_path}"
            )

        col_map = {}
        if "datetime" in df.columns and "trade_date" not in df.columns:
            col_map["datetime"] = "trade_date"
        if "instrument" in df.columns and "ts_code" not in df.columns:
            col_map["instrument"] = "ts_code"

        if col_map:
            df = df.rename(col_map)

        if "trade_date" in df.columns:
            if df.schema["trade_date"] == pl.Utf8:
                df = df.with_columns(pl.col("trade_date").str.to_date())
            elif df.schema["trade_date"] == pl.Datetime:
                df = df.with_columns(pl.col("trade_date").dt.date())

        df = df.filter((pl.col("trade_date") >= start) & (pl.col("trade_date") <= end))

        # 命名 universe（all / 指数 / 转债）不按代码过滤；列表则按代码过滤
        named = {
            "all",
            "csi300",
            "csi500",
            "csi1000",
            "全a股",
            "全A股",
            *{a.lower() for a in _CB_UNIVERSE_ALIASES},
        }
        if isinstance(universe, str):
            u_key = universe.strip()
            if u_key and u_key.lower() not in named and "转债" not in u_key and "股" not in u_key:
                df = df.filter(pl.col("ts_code").is_in([universe]))
            # else: keep full panel for named universes
        elif isinstance(universe, list):
            df = df.filter(pl.col("ts_code").is_in(universe))

        required_cols = ["trade_date", "ts_code", "open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ReproductionError(f"Local data missing required columns: {missing}")

        return df

    def _empty_price_frame(self) -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "ts_code": pl.Utf8,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
                "amount": pl.Float64,
            }
        )

    def _load_ricequant_price(
        self, universe: str | list[str], start: date, end: date
    ) -> pl.DataFrame:
        """米筐日频量价；命名股票池解析为指数成分；结果进程内缓存。"""
        try:
            rqdatac = self._ensure_rqdatac_init()
            instruments = self._resolve_ricequant_instruments(universe, as_of=end)
            if not instruments:
                logger.warning("Resolved empty instruments for universe=%r", universe)
                return self._empty_price_frame()

            # 缓存键 v2：含市值字段版本
            cache_key = (
                "v2|" + ",".join(sorted(instruments)[:50]) + f"|n={len(instruments)}",
                start.isoformat(),
                end.isoformat(),
            )
            if cache_key in _RQ_PRICE_CACHE:
                return _RQ_PRICE_CACHE[cache_key]

            # 磁盘缓存（跨 CLI 子进程）
            import hashlib

            digest = hashlib.sha256(
                f"{cache_key[0]}|{cache_key[1]}|{cache_key[2]}".encode()
            ).hexdigest()[:24]
            disk_path = _RQ_DISK_CACHE_DIR / f"{digest}.parquet"
            if disk_path.exists():
                try:
                    pldf = pl.read_parquet(disk_path)
                    _RQ_PRICE_CACHE[cache_key] = pldf
                    logger.info(
                        "ricequant price disk-cache hit: %s rows=%d",
                        disk_path.name,
                        pldf.height,
                    )
                    return pldf
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ricequant disk cache read failed: %s", exc)

            df = rqdatac.get_price(
                instruments,
                start_date=start,
                end_date=end,
                frequency="1d",
                fields=["open", "high", "low", "close", "volume", "total_turnover"],
            )

            if df is None or getattr(df, "empty", True):
                empty = self._empty_price_frame()
                _RQ_PRICE_CACHE[cache_key] = empty
                return empty

            df = df.reset_index()

            col_map = {}
            if "date" in df.columns:
                col_map["date"] = "trade_date"
            if "order_book_id" in df.columns:
                col_map["order_book_id"] = "ts_code"
            if "total_turnover" in df.columns:
                col_map["total_turnover"] = "amount"

            df = df.rename(columns=col_map)

            pldf = pl.from_pandas(df)
            if "trade_date" in pldf.columns and pldf.schema["trade_date"] == pl.Datetime:
                pldf = pldf.with_columns(pl.col("trade_date").dt.date())
            # 保证 amount 列存在
            if "amount" not in pldf.columns:
                pldf = pldf.with_columns(pl.lit(None).cast(pl.Float64).alias("amount"))

            # 一等公民：拼接市值（供 size/value 类公式直接使用，非运行期 fallback）
            pldf = self._join_ricequant_market_cap(rqdatac, pldf, instruments, start, end)

            _RQ_PRICE_CACHE[cache_key] = pldf
            try:
                _RQ_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                pldf.write_parquet(disk_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ricequant disk cache write failed: %s", exc)

            logger.info(
                "ricequant price loaded: universe=%r instruments=%d rows=%d",
                universe if isinstance(universe, str) else f"list[{len(universe)}]",
                len(instruments),
                pldf.height,
            )
            return pldf
        except (ConfigurationError, ReproductionError):
            raise
        except Exception as e:
            raise ReproductionError(f"Failed to fetch data from ricequant: {e}") from e

    def _join_ricequant_market_cap(
        self,
        rqdatac: Any,
        pldf: pl.DataFrame,
        instruments: list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        if "market_cap" in pldf.columns:
            return pldf
        try:
            mcap = rqdatac.get_factor(
                instruments,
                factor="market_cap",
                start_date=start,
                end_date=end,
            )
            if mcap is None or getattr(mcap, "empty", True):
                return pldf
            mcap = mcap.reset_index()
            col_map = {}
            if "date" in mcap.columns:
                col_map["date"] = "trade_date"
            if "order_book_id" in mcap.columns:
                col_map["order_book_id"] = "ts_code"
            if col_map:
                mcap = mcap.rename(columns=col_map)
            mpdf = pl.from_pandas(mcap)
            if "trade_date" in mpdf.columns and mpdf.schema["trade_date"] == pl.Datetime:
                mpdf = mpdf.with_columns(pl.col("trade_date").dt.date())
            if "market_cap" not in mpdf.columns:
                # single factor series name may vary
                for c in mpdf.columns:
                    if c not in {"trade_date", "ts_code"}:
                        mpdf = mpdf.rename({c: "market_cap"})
                        break
            if "market_cap" not in mpdf.columns:
                return pldf
            keep = mpdf.select(["trade_date", "ts_code", "market_cap"])
            out = pldf.join(keep, on=["trade_date", "ts_code"], how="left")
            # 别名列：与提取规范化 / 公式字段一致
            out = out.with_columns(pl.col("market_cap").alias("total_market_cap"))
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("ricequant market_cap join skipped: %s", exc)
            return pldf

    def _load_qlib_price(self, universe: str | list[str], start: date, end: date) -> pl.DataFrame:
        import importlib.util

        if importlib.util.find_spec("qlib") is None:
            raise ConfigurationError(
                "qlib is not installed. Please install it to use qlib data source."
            )

        if not self.settings.qlib_data_path:
            raise ConfigurationError("qlib_data_path is not configured.")

        import qlib
        from qlib.config import REG_CN
        from qlib.data import D

        # Init Qlib
        qlib.init(provider_uri=self.settings.qlib_data_path, region=REG_CN)

        instruments: str | list[str]
        if universe == "all":
            instruments = "all"
        elif isinstance(universe, str):
            instruments = [universe]
        else:
            instruments = universe

        fields = ["$open", "$high", "$low", "$close", "$volume", "$amount"]
        try:
            df = D.features(
                instruments,
                fields,
                start_time=start.strftime("%Y-%m-%d"),
                end_time=end.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            raise ReproductionError(f"Qlib data fetch failed: {e}") from e

        if df is None or df.empty:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "ts_code": pl.Utf8,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                    "amount": pl.Float64,
                }
            )

        df = df.reset_index()
        col_map = {
            "datetime": "trade_date",
            "instrument": "ts_code",
            "$open": "open",
            "$high": "high",
            "$low": "low",
            "$close": "close",
            "$volume": "volume",
            "$amount": "amount",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        pldf = pl.from_pandas(df)
        if "trade_date" in pldf.columns and pldf.schema["trade_date"] == pl.Datetime:
            pldf = pldf.with_columns(pl.col("trade_date").dt.date())

        return pldf

    def _load_tushare_price(
        self, universe: str | list[str], start: date, end: date
    ) -> pl.DataFrame:
        try:
            import tushare as ts
        except ImportError:
            raise ConfigurationError("tushare is not installed. Please install it.")

        # tushare token
        token = (
            self.settings.tushare_token.get_secret_value() if self.settings.tushare_token else None
        )
        if not token:
            raise ConfigurationError("tushare_token is not configured in settings.")

        ts.set_token(token)
        pro = ts.pro_api()

        if isinstance(universe, str) and universe != "all":
            universe = [universe]

        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        dfs = []
        try:
            if universe == "all":
                # download by trade dates (might be slow for many dates, but necessary for 'all')
                cal = pro.trade_cal(
                    exchange="SSE",
                    start_date=start_str,
                    end_date=end_str,
                    is_open="1",
                )
                dates = cal["cal_date"].tolist()
                for d in dates:
                    df = pro.daily(trade_date=d)
                    if not df.empty:
                        dfs.append(df)
            else:
                # download by ts_code
                for code in universe:
                    df = pro.daily(ts_code=code, start_date=start_str, end_date=end_str)
                    if not df.empty:
                        dfs.append(df)
        except Exception as e:
            raise ReproductionError(f"Tushare data fetch failed: {e}")

        import pandas as pd

        if not dfs:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "ts_code": pl.Utf8,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                    "amount": pl.Float64,
                }
            )
        combined = pd.concat(dfs, ignore_index=True)

        pldf = pl.from_pandas(combined)

        if "trade_date" in pldf.columns:
            pldf = pldf.with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d"))

        # rename vol -> volume if exists
        if "vol" in pldf.columns and "volume" not in pldf.columns:
            pldf = pldf.rename({"vol": "volume"})

        return pldf

    # ── 基本面数据加载实现 ──

    # 研报术语 → 规范化字段名的映射
    FUNDAMENTAL_FIELD_MAP: dict[str, str] = {
        # 估值
        "pe": "pe_ttm",
        "市盈率": "pe_ttm",
        "pe_ttm": "pe_ttm",
        "pb": "pb",
        "市净率": "pb",
        "ps": "ps_ttm",
        "市销率": "ps_ttm",
        # 盈利
        "roe": "roe_ttm",
        "净资产收益率": "roe_ttm",
        "roe_ttm": "roe_ttm",
        "roa": "roa_ttm",
        "总资产收益率": "roa_ttm",
        "roa_ttm": "roa_ttm",
        "grossprofit_margin": "grossprofit_margin",
        "毛利率": "grossprofit_margin",
        "netprofit_margin": "netprofit_margin",
        "净利率": "netprofit_margin",
        # 成长
        "revenue_yoy": "revenue_yoy",
        "营收增速": "revenue_yoy",
        "profit_yoy": "profit_yoy",
        "净利润增速": "profit_yoy",
        # 规模与流动性
        "market_cap": "market_cap",
        "总市值": "market_cap",
        "float_market_cap": "float_market_cap",
        "流通市值": "float_market_cap",
        "turnover_rate": "turnover_rate",
        "换手率": "turnover_rate",
        "turnover": "turnover_rate",
        # 质量
        "debt_to_equity": "debt_to_equity",
        "资产负债率": "debt_to_equity",
        "current_ratio": "current_ratio",
        "流动比率": "current_ratio",
        # 股息
        "dividend_yield": "dividend_yield",
        "股息率": "dividend_yield",
        # ── 转债专用 ──
        "ytm": "ytm",
        "YTM": "ytm",
        "到期收益率": "ytm",
        "债性": "ytm",
        "premium_rate": "premium_rate",
        "平价溢价率": "premium_rate",
        "转股溢价率": "premium_rate",
        "溢价率": "premium_rate",
        "bond_value": "bond_value",
        "债底": "bond_value",
        "纯债价值": "bond_value",
        "implied_vol": "implied_vol",
        "隐波": "implied_vol",
        "隐含波动率": "implied_vol",
        "option_value": "option_value",
        "期权价值": "option_value",
        "remaining_size": "remaining_size",
        "剩余规模": "remaining_size",
        "余额": "remaining_size",
        "conversion_price": "conversion_price",
        "转股价": "conversion_price",
        # qlib 风格字段引用映射
        "$roe": "roe_ttm",
        "$pe": "pe_ttm",
        "$pb": "pb",
        "$market_cap": "market_cap",
        "$turnover_rate": "turnover_rate",
        "$ytm": "ytm",
        "$premium_rate": "premium_rate",
    }

    @classmethod
    def resolve_fundamental_fields(cls, report_fields: list[str]) -> list[str]:
        """将研报术语映射为规范化字段名，未知字段原样保留。"""
        return [cls.FUNDAMENTAL_FIELD_MAP.get(f, f) for f in report_fields]

    def _load_local_fundamental(self, fields: list[str], start: date, end: date) -> pl.DataFrame:
        data_path = self.settings.local_data_path
        if data_path is None:
            data_path = Path("tests/fixtures/test_data")
        fund_path = data_path / "fundamentals.parquet"

        if not fund_path.exists():
            # 无基本面文件时返回空 DataFrame（schema 正确），便于离线测试
            schema: dict[str, Any] = {"trade_date": pl.Date, "ts_code": pl.Utf8}
            for f in fields:
                schema[f] = pl.Float64
            return pl.DataFrame(schema=schema)

        df = pl.read_parquet(fund_path)

        # 列名规范化
        col_map = {}
        if "datetime" in df.columns and "trade_date" not in df.columns:
            col_map["datetime"] = "trade_date"
        if "instrument" in df.columns and "ts_code" not in df.columns:
            col_map["instrument"] = "ts_code"
        if col_map:
            df = df.rename(col_map)

        # 日期过滤
        if "trade_date" in df.columns:
            if df.schema["trade_date"] == pl.Utf8:
                df = df.with_columns(pl.col("trade_date").str.to_date())
            elif df.schema["trade_date"] == pl.Datetime:
                df = df.with_columns(pl.col("trade_date").dt.date())
            df = df.filter((pl.col("trade_date") >= start) & (pl.col("trade_date") <= end))

        # 只取需要的列
        available = [c for c in fields if c in df.columns]
        keep = ["trade_date", "ts_code"] + available
        keep = [c for c in keep if c in df.columns]
        return df.select(keep) if keep else df

    def _load_ricequant_fundamental(
        self, fields: list[str], start: date, end: date
    ) -> pl.DataFrame:
        try:
            import rqdatac
        except ImportError:
            raise ConfigurationError(
                "rqdatac is not installed. Install with: uv sync --extra ricequant"
            )

        # rqdatac 基本面字段映射
        rq_field_map: dict[str, str] = {
            "pe_ttm": "pe_ratio_ttm",
            "pb": "pb_ratio",
            "ps_ttm": "ps_ratio_ttm",
            "roe_ttm": "roe_ttm",
            "roa_ttm": "roa_ttm",
            "market_cap": "market_cap",
            "float_market_cap": "float_market_cap",
            "turnover_rate": "turnover_rate",
            "dividend_yield": "dividend_yield",
        }

        # 获取全 A 股列表
        try:
            all_stocks = rqdatac.all_instruments(type="CS", date=end)
            if all_stocks is None or all_stocks.empty:
                return pl.DataFrame(
                    schema={
                        "trade_date": pl.Date,
                        "ts_code": pl.Utf8,
                        **{f: pl.Float64 for f in fields},
                    }
                )
            order_book_ids = all_stocks["order_book_id"].tolist()
        except Exception:
            order_book_ids = []

        if not order_book_ids:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "ts_code": pl.Utf8,
                    **{f: pl.Float64 for f in fields},
                }
            )

        # 逐字段获取
        frames: list[pl.DataFrame] = []
        for field in fields:
            rq_field = rq_field_map.get(field, field)
            try:
                series = rqdatac.get_factor(
                    order_book_ids, rq_field, start_date=start, end_date=end
                )
                if series is not None and not series.empty:
                    sdf = series.reset_index()
                    sdf.columns = (
                        ["trade_date", "ts_code", field]
                        if len(sdf.columns) == 3
                        else sdf.columns.tolist()
                    )
                    frames.append(pl.from_pandas(sdf))
            except Exception:
                continue

        if not frames:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "ts_code": pl.Utf8,
                    **{f: pl.Float64 for f in fields},
                }
            )

        # join all fields on trade_date + ts_code
        result = frames[0]
        for fdf in frames[1:]:
            result = result.join(fdf, on=["trade_date", "ts_code"], how="outer")
        return result

    def _load_tushare_fundamental(self, fields: list[str], start: date, end: date) -> pl.DataFrame:
        try:
            import tushare as ts
        except ImportError:
            raise ConfigurationError(
                "tushare is not installed. Install with: uv sync --extra tushare"
            )

        token = (
            self.settings.tushare_token.get_secret_value() if self.settings.tushare_token else None
        )
        if not token:
            raise ConfigurationError("tushare_token is not configured in settings.")

        ts.set_token(token)
        pro = ts.pro_api()

        end_str = end.strftime("%Y%m%d")

        # daily_basic → pe_ttm, pb, turnover_rate, market_cap
        daily_fields: list[str] = []
        ts_daily_map = {
            "pe_ttm": "pe_ttm",
            "pb": "pb",
            "ps_ttm": "ps_ttm",
            "turnover_rate": "turnover_rate",
            "market_cap": "total_mv",
            "float_market_cap": "circ_mv",
        }
        for f in fields:
            if f in ts_daily_map:
                daily_fields.append(ts_daily_map[f])

        results: dict[str, pl.DataFrame] = {}

        if daily_fields:
            try:
                df = pro.daily_basic(
                    trade_date=end_str,
                    fields=f"ts_code,trade_date,{','.join(daily_fields)}",
                )
                if df is not None and not df.empty:
                    pldf = pl.from_pandas(df)
                    pldf = pldf.with_columns(pl.col("trade_date").str.strptime(pl.Date, "%Y%m%d"))
                    # 反向映射回规范名
                    rev_map = {v: k for k, v in ts_daily_map.items() if v in pldf.columns}
                    pldf = pldf.rename({v: k for k, v in rev_map.items()})
                    results["daily"] = pldf.select(
                        ["trade_date", "ts_code"]
                        + [c for c in pldf.columns if c not in ("trade_date", "ts_code")]
                    )
            except Exception:
                pass

        # fina_indicator → roe, roa, gp_margin, np_margin, debt_to_equity, etc.
        fina_fields: list[str] = []
        ts_fina_map = {
            "roe_ttm": "roe",
            "roa_ttm": "roa",
            "grossprofit_margin": "grossprofit_margin",
            "netprofit_margin": "netprofit_margin",
            "revenue_yoy": "or_yoy",
            "profit_yoy": "profit_dedt",
            "debt_to_equity": "debt_to_assets",
            "current_ratio": "current_ratio",
            "dividend_yield": "dv_ratio",
        }
        for f in fields:
            if f in ts_fina_map:
                fina_fields.append(ts_fina_map[f])

        if fina_fields:
            try:
                df = pro.fina_indicator(
                    end_date=end_str,
                    fields=f"ts_code,end_date,{','.join(fina_fields)}",
                )
                if df is not None and not df.empty:
                    pldf = pl.from_pandas(df)
                    if "end_date" in pldf.columns:
                        pldf = pldf.with_columns(
                            pl.col("end_date").str.strptime(pl.Date, "%Y%m%d").alias("trade_date")
                        ).drop("end_date")
                    rev_map = {v: k for k, v in ts_fina_map.items() if v in pldf.columns}
                    pldf = pldf.rename(rev_map)
                    results["fina"] = pldf.select(
                        ["trade_date", "ts_code"]
                        + [c for c in pldf.columns if c not in ("trade_date", "ts_code")]
                    )
            except Exception:
                pass

        if not results:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "ts_code": pl.Utf8,
                    **{f: pl.Float64 for f in fields},
                }
            )

        merged = list(results.values())[0]
        for other in list(results.values())[1:]:
            merged = merged.join(other, on=["trade_date", "ts_code"], how="outer")
        return merged

    def _load_qlib_fundamental(self, fields: list[str], start: date, end: date) -> pl.DataFrame:
        try:
            import qlib
            from qlib.data import D

            qlib.init(
                provider_uri=self.settings.qlib_data_path,
                region="cn" if self.settings.qlib_data_path else "cn",
            )
            # qlib fundamental fields use $ prefix
            qlib_fields = [f"${f}" for f in fields]
            df = D.features(
                "all",
                qlib_fields,
                start_time=start.strftime("%Y-%m-%d"),
                end_time=end.strftime("%Y-%m-%d"),
            )
            if df is None or df.empty:
                return pl.DataFrame(
                    schema={
                        "trade_date": pl.Date,
                        "ts_code": pl.Utf8,
                        **{f: pl.Float64 for f in fields},
                    }
                )
            df = df.reset_index()
            df = df.rename(
                columns={
                    "datetime": "trade_date",
                    "instrument": "ts_code",
                    **{f"${f}": f for f in fields},
                }
            )
            return pl.from_pandas(df)
        except ImportError:
            raise ConfigurationError("qlib is not installed.")
        except Exception:
            return pl.DataFrame(
                schema={
                    "trade_date": pl.Date,
                    "ts_code": pl.Utf8,
                    **{f: pl.Float64 for f in fields},
                }
            )
