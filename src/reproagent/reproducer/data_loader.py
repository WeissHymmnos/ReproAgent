"""量价 / 基本面数据加载。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

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
        """基本面字段，如 roe_ttm, pe_ttm, turnover_rate。"""
        if self.settings.data_source == "local":
            schema = {"trade_date": pl.Date, "ts_code": pl.Utf8}
            for f in fields:
                schema[f] = pl.Float64
            return pl.DataFrame(schema=schema)
        else:
            raise ConfigurationError(
                f"Fundamental data not configured for {self.settings.data_source}"
            )

    def _load_local_price(
        self, universe: str | list[str], start: date, end: date
    ) -> pl.DataFrame:
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

    def _load_qlib_price(
        self, universe: str | list[str], start: date, end: date
    ) -> pl.DataFrame:
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
            "$amount": "amount"
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
            self.settings.tushare_token.get_secret_value()
            if self.settings.tushare_token
            else None
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
                    exchange='SSE',
                    start_date=start_str,
                    end_date=end_str,
                    is_open='1',
                )
                dates = cal['cal_date'].tolist()
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
