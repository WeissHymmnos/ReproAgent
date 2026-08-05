"""量价 / 基本面数据加载。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from reproagent.exceptions import ConfigurationError, ReproductionError
from reproagent.settings import Settings


class DataLoader:
    """从 ricequant / tushare / local 加载为 Polars DataFrame。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_price_data(
        self,
        universe: str | list[str],
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """日频量价：trade_date, ts_code, open, high, low, close, volume, amount。"""
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

    def _load_local_price(self, universe: str | list[str], start: date, end: date) -> pl.DataFrame:
        data_path = self.settings.local_data_path
        if data_path is None:
            data_path = Path("tests/fixtures/test_data")
            if not data_path.exists():
                raise ConfigurationError(
                    "local_data_path is not set and tests/fixtures/test_data does not exist."
                )

        parquet_file = data_path / "prices.parquet"
        csv_file = data_path / "prices.csv"

        if parquet_file.exists():
            df = pl.read_parquet(parquet_file)
        elif csv_file.exists():
            df = pl.read_csv(csv_file)
        else:
            raise ConfigurationError(f"No prices.parquet or prices.csv found in {data_path}")

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

        if universe != "all":
            if isinstance(universe, str):
                universe = [universe]
            df = df.filter(pl.col("ts_code").is_in(universe))

        required_cols = ["trade_date", "ts_code", "open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ReproductionError(f"Local data missing required columns: {missing}")

        return df

    def _load_ricequant_price(
        self, universe: str | list[str], start: date, end: date
    ) -> pl.DataFrame:
        try:
            import rqdatac
        except ImportError:
            raise ConfigurationError(
                "rqdatac is not installed. Please install it to use ricequant data source."
            )

        try:
            if isinstance(universe, str) and universe != "all":
                universe = [universe]
            if universe == "all":
                raise ReproductionError(
                    "universe='all' is not supported for ricequant without explicit list"
                )

            df = rqdatac.get_price(
                universe,
                start_date=start,
                end_date=end,
                frequency="1d",
                fields=["open", "high", "low", "close", "volume", "total_turnover"],
            )
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
                    }
                )

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

            return pldf
        except Exception as e:
            raise ReproductionError(f"Failed to fetch data from ricequant: {e}")

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
        # qlib 风格字段引用映射
        "$roe": "roe_ttm",
        "$pe": "pe_ttm",
        "$pb": "pb",
        "$market_cap": "market_cap",
        "$turnover_rate": "turnover_rate",
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
