"""数据质量过滤器：剔除 ST、停牌、新股、涨跌停，确保复现口径一致。

与 ``FactorReproducer`` 集成：在因子计算前先调用 ``apply_guards()``，
过滤统计写入 ``BacktestResult`` metadata。

参考实现：
- zer0factor: docs 中列出的因子值应滤除 ST/停牌/上市天数
- RDAgent: 检查是否引入未来函数时同时检查数据筛选条件
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import polars as pl
from pydantic import BaseModel


class DataGuardConfig(BaseModel):
    """数据口径守卫配置。"""

    filter_st: bool = True
    filter_suspended: bool = True
    min_listing_days: int = 60
    filter_limit_up_down: bool = True
    limit_up_threshold: float = 0.098
    limit_down_threshold: float = -0.098
    require_forward_adjusted: bool = True
    adjustment_field: str = "adj_factor"


@dataclass
class DataGuardStats:
    """过滤过程统计，用于审计和调试。"""

    total_before: int = 0
    total_after: int = 0
    st_removed: int = 0
    suspended_removed: int = 0
    new_listing_removed: int = 0
    limit_up_removed: int = 0
    limit_down_removed: int = 0
    details: dict[str, Any] = field(default_factory=dict)


def _filter_st(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """剔除 ST 和 *ST 股票。

    通过 ``ts_code`` 或 ``name`` 字段中是否含 'ST' 判断。
    匹配模式：*ST, ST 前缀, 或 ST 后跟非字母（如 ST平安）。
    """
    before = len(df)
    st_pattern = r"(?i)(?:\*?ST|ST\*|\*ST)"

    if "name" in df.columns:
        df = df.filter(~pl.col("name").str.contains(st_pattern, literal=False))
    if "ts_code" in df.columns:
        df = df.filter(~pl.col("ts_code").str.contains(st_pattern, literal=False))
    return df, before - len(df)


def _filter_suspended(df: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """剔除停牌观测。

    判断依据：volume == 0 或 status 字段为 'suspended'。
    """
    before = len(df)
    if "volume" in df.columns:
        df = df.filter(pl.col("volume") > 0)
    if "status" in df.columns:
        df = df.filter(pl.col("status") != "suspended")
    return df, before - len(df)


def _filter_new_listings(df: pl.DataFrame, min_days: int) -> tuple[pl.DataFrame, int]:
    """剔除上市不足 ``min_days`` 个自然日的股票。

    需要 ``list_date`` 或 ``ipo_date`` 字段与 ``trade_date`` 比较。
    如果数据中没有上市日期字段，跳过并记录警告。
    """
    before = len(df)
    list_col = None
    if "list_date" in df.columns:
        list_col = "list_date"
    elif "ipo_date" in df.columns:
        list_col = "ipo_date"
    else:
        # 数据不支持，跳过
        return df, 0

    if df.schema[list_col] in (pl.Utf8,):
        df = df.with_columns(pl.col(list_col).str.to_date())

    df = df.filter((pl.col("trade_date") - pl.col(list_col)).dt.total_days() >= min_days)
    return df, before - len(df)


def _filter_limit_hit(df: pl.DataFrame, config: DataGuardConfig) -> tuple[pl.DataFrame, int, int]:
    """剔除当日触及涨跌停的观测。

    对需要 ``pre_close`` 字段计算张跌幅。如果没有该字段但存在
    复权因子，则通过 ``close / Ref(close, 1) - 1`` 估算。

    返回 (filtered_df, limit_up_count, limit_down_count)。
    """
    up_removed = 0
    down_removed = 0

    if "pre_close" not in df.columns and "close" in df.columns:
        if "ts_code" in df.columns:
            df = df.sort(["ts_code", "trade_date"]).with_columns(
                pl.col("close").shift(1).over("ts_code").alias("pre_close")
            )
        elif "asset" in df.columns:
            df = df.sort(["asset", "date"]).with_columns(
                pl.col("close").shift(1).over("asset").alias("pre_close")
            )
            if "trade_date" not in df.columns and "date" in df.columns:
                df = df.rename({"date": "trade_date"})

    if "pre_close" in df.columns:
        df = df.with_columns(
            ((pl.col("close") - pl.col("pre_close")) / pl.col("pre_close")).alias("_daily_return")
        )
        up_mask = pl.col("_daily_return") > config.limit_up_threshold
        down_mask = pl.col("_daily_return") < config.limit_down_threshold
        # Null return (first bar / missing pre_close) is not a limit hit; Polars
        # filter() drops null predicates, which silently deleted session-1 rows.
        up_hit = up_mask.fill_null(False)
        down_hit = down_mask.fill_null(False)
        up_removed = int(df.select(up_hit.sum()).item() or 0)
        down_removed = int(df.select(down_hit.sum()).item() or 0)
        df = df.filter(~(up_hit | down_hit))
        df = df.drop("_daily_return")

    # 清理临时列
    for tmp_col in ["pre_close"]:
        if tmp_col in df.columns and tmp_col not in ("open", "high", "low", "close", "volume"):
            df = df.drop(tmp_col)

    return df, up_removed, down_removed


def validate_adjustment(df: pl.DataFrame) -> tuple[bool, str]:
    """检查价格是否可能为后复权。

    通过检查 close 的相邻日比率是否有断崖式跳变
    （除权缺口 > 30%）来判断。这只是一个启发式检测。
    """
    if "close" not in df.columns:
        return False, "缺少 close 列，无法检查复权"

    if "adj_factor" in df.columns:
        # 有权因子则直接检查
        if df["adj_factor"].std() > 0:
            return True, "检测到非恒定复权因子"
        return False, "复权因子恒为 1，可能未经复权调整"

    # 无复权因子，用收益率跳变扫描
    sort_col = "ts_code" if "ts_code" in df.columns else "asset"
    date_col = "trade_date" if "trade_date" in df.columns else "date"
    df_sorted = df.sort([sort_col, date_col])
    returns = df_sorted.with_columns(
        (pl.col("close") / pl.col("close").shift(1).over(sort_col) - 1).alias("_r")
    ).drop_nulls("_r")
    jump_count = len(returns.filter(pl.col("_r").abs() > 0.3))
    if jump_count > len(returns) * 0.01:
        return False, f"检测到 {jump_count} 个收益率跳变 (>30%)，可能包含除权缺口"
    return True, ""


# ── 字段名规范化 ──

_STANDARD_COL_MAP: dict[str, str] = {
    "date": "trade_date",
    "datetime": "trade_date",
    "instrument": "ts_code",
    "asset": "ts_code",
    "order_book_id": "ts_code",
}


def _normalize_columns(df: pl.DataFrame) -> pl.DataFrame:
    """将常见列名规范化为统一格式。

    仅当源列存在且目标列不存在时才进行重命名，避免重复列冲突。
    """
    renames = {
        k: v for k, v in _STANDARD_COL_MAP.items() if k in df.columns and v not in df.columns
    }
    if renames:
        df = df.rename(renames)
    return df


def apply_guards(
    df: pl.DataFrame,
    config: DataGuardConfig | None = None,
) -> tuple[pl.DataFrame, DataGuardStats]:
    """依次应用所有数据口径守卫，返回 (过滤后数据, 统计)。

    Parameters
    ----------
    df:
        原始宽表面板（单资产或多资产 daily data）。
    config:
        守卫配置，为 ``None`` 时使用默认配置。

    Returns
    -------
    tuple[pl.DataFrame, DataGuardStats]:
        过滤后的 DataFrame 和过滤统计。
    """
    if config is None:
        config = DataGuardConfig()

    df = _normalize_columns(df)
    stats = DataGuardStats(total_before=len(df))

    if config.filter_st:
        df, removed = _filter_st(df)
        stats.st_removed = removed

    if config.filter_suspended:
        df, removed = _filter_suspended(df)
        stats.suspended_removed = removed

    if config.min_listing_days > 0:
        df, removed = _filter_new_listings(df, config.min_listing_days)
        stats.new_listing_removed = removed

    if config.filter_limit_up_down:
        df, up, down = _filter_limit_hit(df, config)
        stats.limit_up_removed = up
        stats.limit_down_removed = down

    stats.total_after = len(df)

    if config.require_forward_adjusted:
        valid, msg = validate_adjustment(df)
        stats.details["adjustment_valid"] = valid
        stats.details["adjustment_detail"] = msg

    return df, stats
