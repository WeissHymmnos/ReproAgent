"""反过拟合统计检验套件。

实现 masterplan (§4.2) 引用的 alpha-lens 风格偏差门控逻辑：

- DSR (Deflated Sharpe Ratio): 多重检验校正后的 Sharpe
- PBO (Probability of Backtest Overfitting): 组合交叉验证过拟合概率
- MinBTL (Minimum Backtest Length): 给定 Sharpe 下所需最小样本量
- Bootstrap Sharpe CI: 百分位 bootstrap 置信区间
- Walk-Forward Validation: expanding/rolling 窗口的样本外 IC
- Subsample Stress Test: 分牛/熊/震荡市的 IC 稳定性
- Placebo Test: 安慰剂检验

参考：
- Bailey & López de Prado (2014): "The Deflated Sharpe Ratio"
- Bailey et al. (2017): "The Probability of Backtest Overfitting"
- QuantGPT: 4 项反过拟合检验 + walk-forward 验证器
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl

# ── 辅助函数 ──


def _phi(x: float) -> float:
    """标准正态 CDF。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """标准正态 PPF（分位数函数），用 Abramowitz & Stegun 近似。"""
    if p <= 0.0:
        return -np.inf
    if p >= 1.0:
        return np.inf
    # 有理逼近（精度 ~1e-4）
    a = [2.50662823884, -18.61500062529, 41.39119773534, -25.44106049637]
    b = [-8.47351093090, 23.08336743743, -21.06224101826, 3.13082909833]
    c = [
        0.3374754822726147,
        0.9761690190917186,
        0.1607979714918209,
        0.0276438810333863,
        0.0038405729373609,
        0.0003951896511919,
        0.0000321767881768,
        0.0000002888167364,
        0.0000003960315187,
    ]
    y = p - 0.5
    if abs(y) < 0.42:
        r = y * y
        x = (
            y
            * (((a[3] * r + a[2]) * r + a[1]) * r + a[0])
            / ((((b[3] * r + b[2]) * r + b[1]) * r + b[0]) * r + 1.0)
        )
    else:
        r = p if y > 0 else 1.0 - p
        r = math.log(-math.log(r))
        x = (
            c[0]
            + r * c[1]
            + r * r * c[2]
            + r * r * r * c[3]
            + r * r * r * r * c[4]
            + r * r * r * r * r * c[5]
            + r * r * r * r * r * r * c[6]
            + r * r * r * r * r * r * r * c[7]
            + r * r * r * r * r * r * r * r * c[8]
        )
        if y < 0:
            x = -x
    return x


def _sharpe_ratio(returns: np.ndarray, freq: int = 252) -> float:
    """年化夏普比率。"""
    mu = np.mean(returns)
    sigma = np.std(returns, ddof=1)
    if sigma == 0:
        return 0.0
    return (mu / sigma) * math.sqrt(freq)


# ── 结果数据类 ──


@dataclass
class DSRResult:
    """Deflated Sharpe Ratio 结果。"""

    dsr: float  # DSR 值（越低越可能过拟合）
    psr: float  # Probabilistic Sharpe Ratio
    p_value: float  # DSR 的 p 值
    deflated: bool  # DSR < 0.05 则标记为可能过拟合


@dataclass
class PBOResult:
    """Probability of Backtest Overfitting 结果。"""

    pbo: float  # 过拟合概率 (0–1)
    n_combinations: int  # 组合交叉验证的 split 组合数
    is_sharpe_rank: float  # 样本内 Sharpe 排名
    oos_sharpe_rank: float  # 样本外 Sharpe 排名
    overfit: bool  # PBO > 0.5 → 可能过拟合


@dataclass
class MinBTLResult:
    """Minimum Backtest Length 结果。"""

    min_obs: int  # 所需最小观测数
    actual_obs: int  # 实际观测数
    sufficient: bool  # actual_obs >= min_obs


@dataclass
class BootstrapResult:
    """Bootstrap 置信区间结果。"""

    sharpe_ci_lower: float
    sharpe_ci_upper: float
    n_boot: int
    significant: bool  # CI 下界 > 0


@dataclass
class WalkForwardResult:
    """Walk-Forward 验证结果。"""

    ic_oos_mean: float  # 样本外 IC 均值
    ic_oos_std: float
    ic_is_mean: float  # 样本内 IC 均值
    ic_is_std: float
    ic_decay: float  # OOS IC / IS IC 比率 (< 1 正常)
    n_splits: int
    method: str  # "expanding" | "rolling"
    stable: bool  # ic_decay > 0.5 且 ic_oos_mean > 0


@dataclass
class StressTestResult:
    """子样本压力测试结果。"""

    regime_ics: dict[str, float]  # 各市场环境的 IC
    regime_counts: dict[str, int]  # 各环境的样本数
    worst_regime: str  # IC 最低的环境
    consistent: bool  # 所有环境 IC 同号


@dataclass
class PlaceboResult:
    """安慰剂检验结果。"""

    true_ic: float  # 真实 IC
    placebo_mean: float  # 随机打乱后的平均 IC
    placebo_std: float
    p_value: float  # 真实 IC 在打乱分布中的 p 值
    n_shuffles: int
    significant: bool  # p_value < 0.05


# ── 检验实现 ──


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    n_obs: int,
    sharpe_std: float | None = None,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> DSRResult:
    """计算 Deflated Sharpe Ratio。

    Parameters
    ----------
    sharpe: 观测到的年化 Sharpe
    n_trials: 尝试的因子/策略总数（多重检验校正）
    n_obs: 收益率序列的观测数
    sharpe_std: Sharpe 的标准误；如果为 None 则从 skew/kurt 估计
    skew: 收益率偏度
    kurt: 收益率峰度
    """
    if sharpe_std is None:
        sharpe_std = math.sqrt(
            (1.0 + 0.5 * sharpe**2 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe**2) / (n_obs - 1)
        )

    if sharpe_std == 0.0:
        return DSRResult(dsr=0.0, psr=0.0, p_value=1.0, deflated=False)

    # PSR = Probabilistic Sharpe Ratio
    z_stat = sharpe / sharpe_std
    psr = _phi(z_stat)

    # DSR = Φ(Φ⁻¹(max(PSR, 0)) * sqrt(n_trials) - ...)
    # 简化：DSR = Φ( (sharpe_hat - E[max]) / std )
    # 其中 E[max] ≈ sharpe_std * _phi_inv(1 - 1/n_trials)
    # 使用 E[max] = sharpe_std * sqrt(2 * log(n_trials)) 近似
    if n_trials > 1:
        e_max = sharpe_std * math.sqrt(2.0 * math.log(n_trials))
    else:
        e_max = 0.0

    dsr_z = (sharpe - e_max) / sharpe_std
    dsr = _phi(dsr_z)
    p_value = 1.0 - dsr

    return DSRResult(
        dsr=max(dsr, 0.0),
        psr=psr,
        p_value=p_value,
        deflated=dsr < 0.05,
    )


def prob_backtest_overfitting(
    returns: np.ndarray,
    n_splits: int = 5,
    oos_ratio: float = 0.3,
) -> PBOResult:
    """计算 Probability of Backtest Overfitting。

    使用组合交叉验证（Combinatorial Purged Cross-Validation）：
    将收益序列按时间分为 n_splits 段，随机选取 floor(n_splits/2) 段作为 IS，
    其余作为 OOS，计算 C(n_splits, n_splits//2) 种组合的 IS/OOS Sharpe 排名。

    Parameters
    ----------
    returns: 一维收益率数组（日频，按时间排序）
    n_splits: 时间分段数
    oos_ratio: 每段 OOS 的比例（决定 OOS 段的数量）
    """
    n = len(returns)
    if n < n_splits * 2:
        return PBOResult(
            pbo=0.0, n_combinations=0, is_sharpe_rank=0.0, oos_sharpe_rank=0.0, overfit=False
        )

    segment_size = n // n_splits
    from itertools import combinations

    n_is = max(n_splits // 2, 1)
    indices = list(range(n_splits))
    combo_list = list(combinations(indices, n_is))
    n_combinations = len(combo_list)

    if n_combinations < 2:
        return PBOResult(
            pbo=0.0,
            n_combinations=n_combinations,
            is_sharpe_rank=0.0,
            oos_sharpe_rank=0.0,
            overfit=False,
        )

    is_sharpes: list[float] = []
    oos_sharpes: list[float] = []

    for is_set in combo_list:
        is_mask = np.zeros(n, dtype=bool)
        oos_mask = np.zeros(n, dtype=bool)
        for i in range(n_splits):
            start = i * segment_size
            end = start + segment_size if i < n_splits - 1 else n
            if i in is_set:
                is_mask[start:end] = True
            else:
                # OOS: take the last oos_ratio portion of the segment
                oos_start = int(end - segment_size * oos_ratio)
                oos_mask[oos_start:end] = True

        if is_mask.sum() > 1:
            is_sharpes.append(_sharpe_ratio(returns[is_mask]))
        if oos_mask.sum() > 1:
            oos_sharpes.append(_sharpe_ratio(returns[oos_mask]))

    if len(is_sharpes) < 2 or len(oos_sharpes) < 2:
        return PBOResult(
            pbo=0.0,
            n_combinations=n_combinations,
            is_sharpe_rank=0.0,
            oos_sharpe_rank=0.0,
            overfit=False,
        )

    is_arr = np.array(is_sharpes)
    oos_arr = np.array(oos_sharpes)

    # Kendall tau between IS rank and OOS rank
    from scipy.stats import kendalltau

    is_ranks = np.argsort(np.argsort(is_arr))
    oos_ranks = np.argsort(np.argsort(oos_arr))
    tau, _ = kendalltau(is_ranks, oos_ranks)

    # PBO ≈ (1 - tau) / 2
    pbo = (1.0 - max(tau, -1.0)) / 2.0

    mean_is_rank = np.mean(is_ranks) / (len(is_ranks) - 1) if len(is_ranks) > 1 else 0.5
    mean_oos_rank = np.mean(oos_ranks) / (len(oos_ranks) - 1) if len(oos_ranks) > 1 else 0.5

    return PBOResult(
        pbo=pbo,
        n_combinations=n_combinations,
        is_sharpe_rank=mean_is_rank,
        oos_sharpe_rank=mean_oos_rank,
        overfit=pbo > 0.5,
    )


def min_backtest_length(
    sharpe: float,
    variance: float = 0.04,
    alpha: float = 0.05,
) -> MinBTLResult:
    """计算 Minimum Backtest Length。

    给定年化 Sharpe 和收益率方差，计算在显著性水平 α 下
    所需的最小观测数。

    Parameters
    ----------
    sharpe: 年化 Sharpe 比率
    variance: 收益率方差（日度）
    alpha: 显著性水平
    """
    if sharpe <= 0:
        return MinBTLResult(min_obs=int(1e9), actual_obs=0, sufficient=False)

    daily_sharpe = sharpe / math.sqrt(252)
    min_obs = int(math.ceil((variance * (_phi_inv(1.0 - alpha / 2.0)) ** 2) / (daily_sharpe**2)))
    return MinBTLResult(min_obs=min_obs, actual_obs=0, sufficient=False)


def min_backtest_length_check(
    sharpe: float,
    actual_obs: int,
    variance: float = 0.04,
    alpha: float = 0.05,
) -> MinBTLResult:
    """带实际观测数的 MinBTL 检查。"""
    result = min_backtest_length(sharpe, variance, alpha)
    result.actual_obs = actual_obs
    result.sufficient = actual_obs >= result.min_obs
    return result


def bootstrap_sharpe_ci(
    returns: np.ndarray,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> BootstrapResult:
    """百分位 Bootstrap Sharpe 置信区间。"""
    rng = np.random.default_rng(seed)
    n = len(returns)
    sharpes = np.zeros(n_boot)

    for i in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        sharpes[i] = _sharpe_ratio(returns[idx])

    ci_lower = np.percentile(sharpes, alpha / 2.0 * 100)
    ci_upper = np.percentile(sharpes, (1.0 - alpha / 2.0) * 100)

    return BootstrapResult(
        sharpe_ci_lower=ci_lower,
        sharpe_ci_upper=ci_upper,
        n_boot=n_boot,
        significant=ci_lower > 0,
    )


def walk_forward_validation(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
    n_splits: int = 5,
    method: str = "expanding",
) -> WalkForwardResult:
    """Walk-forward 验证：计算样本外 IC。

    将时间序列分为 n_splits 段，逐段训练（计算截面 IC 的均值）、
    在下一段的样本外数据上验证。

    Parameters
    ----------
    factor_values: [date, asset, factor_value]
    forward_returns: [date, asset, forward_return]
    n_splits: 分段数
    method: "expanding"（样本内不断扩展）或 "rolling"（固定窗口）
    """
    df = factor_values.join(forward_returns, on=["date", "asset"], how="inner").drop_nulls()
    if df.is_empty():
        return WalkForwardResult(
            ic_oos_mean=0.0,
            ic_oos_std=0.0,
            ic_is_mean=0.0,
            ic_is_std=0.0,
            ic_decay=1.0,
            n_splits=n_splits,
            method=method,
            stable=False,
        )

    dates = df["date"].unique().sort().to_list()
    if len(dates) < n_splits * 2:
        n_splits = max(len(dates) // 2, 2)

    split_size = len(dates) // n_splits
    ic_is_list: list[float] = []
    ic_oos_list: list[float] = []

    for i in range(n_splits - 1):
        if method == "expanding":
            train_end = min((i + 1) * split_size, len(dates))
            train_dates = dates[:train_end]
        else:
            train_start = max(0, (i - (n_splits - 1)) * split_size)
            train_dates = dates[train_start : (i + 1) * split_size]

        oos_start = (i + 1) * split_size
        oos_end = min((i + 2) * split_size, len(dates))
        oos_dates = dates[oos_start:oos_end]

        if not train_dates or not oos_dates:
            continue

        train_df = df.filter(pl.col("date").is_in(train_dates))
        oos_df = df.filter(pl.col("date").is_in(oos_dates))

        if train_df.is_empty() or oos_df.is_empty():
            continue

        train_ic = train_df.group_by("date").agg(
            pl.corr("factor_value", "forward_return", method="spearman").alias("ic")
        )
        oos_ic = oos_df.group_by("date").agg(
            pl.corr("factor_value", "forward_return", method="spearman").alias("ic")
        )

        if len(train_ic) > 0:
            ic_is_list.append(train_ic["ic"].mean())
        if len(oos_ic) > 0:
            ic_oos_list.append(oos_ic["ic"].mean())

    ic_is_mean = float(np.mean(ic_is_list)) if ic_is_list else 0.0
    ic_is_std = float(np.std(ic_is_list)) if ic_is_list else 0.0
    ic_oos_mean = float(np.mean(ic_oos_list)) if ic_oos_list else 0.0
    ic_oos_std = float(np.std(ic_oos_list)) if ic_oos_list else 0.0

    ic_decay = (ic_oos_mean / ic_is_mean) if ic_is_mean != 0 and ic_oos_mean != 0 else 1.0

    return WalkForwardResult(
        ic_oos_mean=ic_oos_mean,
        ic_oos_std=ic_oos_std,
        ic_is_mean=ic_is_mean,
        ic_is_std=ic_is_std,
        ic_decay=ic_decay,
        n_splits=n_splits,
        method=method,
        stable=(ic_decay > 0.5 and ic_oos_mean > 0),
    )


def subsample_stress_test(
    df: pl.DataFrame,
    returns_col: str = "forward_return",
    index_returns_col: str | None = None,
) -> StressTestResult:
    """子样本压力测试：按市场环境评估 IC 稳定性。

    若提供了 index_returns_col（指数日收益率列），则据此划分市场环境：
    - bull: index daily return > 2 * std
    - bear: index daily return < -2 * std
    - sideways: 其余

    Parameters
    ----------
    df: 包含 date, factor_value, forward_return（和可选的指数收益）的 DataFrame
    returns_col: 前向收益列名
    index_returns_col: 基准指数日收益率列名。为 None 时按 forward_return 自身划分。
    """
    if df.is_empty():
        return StressTestResult(regime_ics={}, regime_counts={}, worst_regime="", consistent=False)

    if index_returns_col and index_returns_col in df.columns:
        ref_col = index_returns_col
    else:
        ref_col = returns_col

    ref_mean = df[ref_col].mean()
    ref_std = df[ref_col].std()
    if ref_std is None or ref_std == 0:
        ref_std = 0.01

    up_threshold = ref_mean + 2.0 * ref_std
    down_threshold = ref_mean - 2.0 * ref_std

    regimes: dict[str, pl.DataFrame] = {}
    regimes["bull"] = df.filter(pl.col(ref_col) > up_threshold)
    regimes["bear"] = df.filter(pl.col(ref_col) < down_threshold)
    regimes["sideways"] = df.filter(
        (pl.col(ref_col) >= down_threshold) & (pl.col(ref_col) <= up_threshold)
    )

    regime_ics: dict[str, float] = {}
    regime_counts: dict[str, int] = {}

    for name, rdf in regimes.items():
        regime_counts[name] = len(rdf)
        if not rdf.is_empty():
            daily_ic = (
                rdf.group_by("date")
                .agg(pl.corr("factor_value", returns_col, method="spearman").alias("ic"))
                .drop_nulls("ic")
            )
            regime_ics[name] = daily_ic["ic"].mean() if len(daily_ic) > 0 else 0.0
        else:
            regime_ics[name] = 0.0

    worst_regime = min(regime_ics, key=regime_ics.get) if regime_ics else ""

    ics = [v for v in regime_ics.values()]
    consistent = all(v > 0 for v in ics) or all(v < 0 for v in ics) if ics else True

    return StressTestResult(
        regime_ics=regime_ics,
        regime_counts=regime_counts,
        worst_regime=worst_regime,
        consistent=consistent,
    )


def placebo_test(
    factor_values: pl.DataFrame,
    forward_returns: pl.DataFrame,
    n_shuffles: int = 100,
    seed: int = 42,
) -> PlaceboResult:
    """安慰剂检验：随机打乱因子值，观察 IC 分布。

    若真实 IC 显著高于打乱分布 → 因子可能含有真实信号。
    """
    rng = np.random.default_rng(seed)
    df = factor_values.join(forward_returns, on=["date", "asset"], how="inner").drop_nulls()

    if df.is_empty():
        return PlaceboResult(
            true_ic=0.0,
            placebo_mean=0.0,
            placebo_std=0.0,
            p_value=1.0,
            n_shuffles=n_shuffles,
            significant=False,
        )

    # 真实 IC
    true_daily_ic = (
        df.group_by("date")
        .agg(pl.corr("factor_value", "forward_return", method="spearman").alias("ic"))
        .drop_nulls("ic")
    )
    true_ic = true_daily_ic["ic"].mean() if len(true_daily_ic) > 0 else 0.0

    factor_vals = df["factor_value"].to_numpy()
    shuffled_ics: list[float] = []

    for _ in range(n_shuffles):
        shuffled = factor_vals.copy()
        rng.shuffle(shuffled)
        df_shuffled = df.with_columns(pl.Series("factor_value_shuffled", shuffled))
        s_daily_ic = (
            df_shuffled.group_by("date")
            .agg(pl.corr("factor_value_shuffled", "forward_return", method="spearman").alias("ic"))
            .drop_nulls("ic")
        )
        if len(s_daily_ic) > 0:
            shuffled_ics.append(s_daily_ic["ic"].mean())
        else:
            shuffled_ics.append(0.0)

    placebo_arr = np.array(shuffled_ics)
    placebo_mean = float(np.mean(placebo_arr))
    placebo_std = float(np.std(placebo_arr)) if len(placebo_arr) > 1 else 1.0

    # 双尾 p 值
    if placebo_std > 0:
        z_stat = abs(true_ic - placebo_mean) / placebo_std
        p_value = 2.0 * (1.0 - _phi(z_stat))
    else:
        p_value = 1.0

    return PlaceboResult(
        true_ic=true_ic,
        placebo_mean=placebo_mean,
        placebo_std=placebo_std,
        p_value=p_value,
        n_shuffles=n_shuffles,
        significant=p_value < 0.05,
    )
