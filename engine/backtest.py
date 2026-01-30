from __future__ import annotations
import numpy as np
import pandas as pd

def infer_periods_per_year(index: pd.DatetimeIndex) -> int:
    inf = pd.infer_freq(index)
    if inf is None:
        return 12
    inf = inf.upper()
    if inf.startswith("M"):
        return 12
    if inf.startswith("Q"):
        return 4
    if inf.startswith("W"):
        return 52
    if inf.startswith("A") or inf.startswith("Y"):
        return 1
    if inf.startswith("B") or inf.startswith("D"):
        return 252
    return 12

def max_drawdown(nav: pd.Series) -> float:
    cm = nav.cummax()
    dd = nav / cm - 1.0
    return float(dd.min())

def downside_std(returns: pd.Series, threshold: float = 0.0) -> float:
    d = returns.copy()
    d[d > threshold] = 0.0
    return float(d.std())

def align_weights_to_returns(returns_df: pd.DataFrame, weights_df: pd.DataFrame) -> pd.DataFrame:
    assets = returns_df.columns.tolist()
    w = weights_df.copy()
    for c in assets:
        if c not in w.columns:
            w[c] = 0.0
    w = w[assets]

    full_idx = returns_df.index.union(w.index)
    w = w.reindex(full_idx).sort_index().ffill()
    w = w.reindex(returns_df.index)

    sums = w.sum(axis=1)
    w = w.div(sums.where(sums != 0, np.nan), axis=0).fillna(0.0)
    return w

def backtest_dynamic_weights_monthly(
    returns_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    rebalance_rule: str,
    starting_capital: float,
    trading_cost_bps: float,
    rf_annual: float,
):
    ppY = infer_periods_per_year(returns_df.index)
    if ppY != 12:
        raise ValueError(f"returns_df 必須是月頻（月末）；目前偵測到 periods_per_year={ppY}")

    w_aligned = align_weights_to_returns(returns_df, weights_df)

    if rebalance_rule == "M":
        rebal_idx = returns_df.resample("M").last().index[:-1]
    elif rebalance_rule == "A":
        rebal_idx = returns_df.resample("A").last().index
    elif rebalance_rule == "Q":
        rebal_idx = returns_df.resample("Q").last().index
    elif rebalance_rule == "2Q-DEC":
        q_end = returns_df.resample("Q").last()
        rebal_idx = q_end[q_end.index.month.isin([6, 12])].index
    else:
        raise ValueError("rebalance_rule 僅支援 M | A | Q | 2Q-DEC")

    cost_rate = trading_cost_bps / 10000.0
    capital = float(starting_capital)
    holdings = capital * w_aligned.iloc[0].values

    values = []
    weights_hist = []

    for dt, r in returns_df.iterrows():
        holdings = holdings * (1 + r.values)
        capital = float(holdings.sum())

        cur_w = holdings / capital if capital != 0 else np.zeros_like(holdings)
        weights_hist.append(pd.Series(cur_w, index=returns_df.columns))

        if dt in rebal_idx:
            next_month = dt + pd.offsets.MonthEnd(1)
            target_w = w_aligned.loc[next_month].values if next_month in w_aligned.index else w_aligned.loc[dt].values
            target_hold = capital * target_w

            traded = np.abs(target_hold - holdings).sum()
            cost = traded * cost_rate
            capital_after = capital - cost

            holdings = capital_after * target_w
            capital = float(holdings.sum())

        values.append(capital)

    nav = pd.Series(values, index=returns_df.index, name=f"NAV_{rebalance_rule}")
    rets = nav.pct_change().fillna(0.0)

    years = len(rets) / 12.0
    total_return = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1.0) if years > 0 else np.nan
    vol_annual = float(rets.std() * np.sqrt(12))

    rf_monthly = rf_annual / 12.0
    excess = rets - rf_monthly
    sharpe = float((excess.mean() * 12) / (rets.std() * np.sqrt(12))) if rets.std() != 0 else np.nan
    dstd = downside_std(rets, threshold=rf_monthly)
    sortino = float((excess.mean() * 12) / (dstd * np.sqrt(12))) if dstd != 0 else np.nan
    mdd = max_drawdown(nav)
    calmar = float(cagr / abs(mdd)) if mdd != 0 else np.nan

    stats = {
        "frequency": "M",
        "rebalance_rule": rebalance_rule,
        "years": float(years),
        "trading_cost_bps": float(trading_cost_bps),
        "rf_annual": float(rf_annual),
        "total_return": float(total_return),
        "CAGR": float(cagr),
        "annualized_vol": float(vol_annual),
        "Sharpe": float(sharpe),
        "Sortino": float(sortino),
        "max_drawdown": float(mdd),
        "Calmar": float(calmar),
        "hit_ratio": float((rets > 0).mean()),
    }

    weights_out = pd.DataFrame(weights_hist, index=returns_df.index, columns=returns_df.columns)
    return nav, rets, weights_out, stats

def run_all_frequencies_monthly(returns_df, weights_df, starting_capital, trading_cost_bps, rf_annual):
    out = {}
    for rule in ["M", "A", "Q", "2Q-DEC"]:
        nav, rets, wts, stats = backtest_dynamic_weights_monthly(
            returns_df, weights_df,
            rebalance_rule=rule,
            starting_capital=starting_capital,
            trading_cost_bps=trading_cost_bps,
            rf_annual=rf_annual,
        )
        out[rule] = {"nav": nav, "returns": rets, "weights": wts, "stats": stats}
    return out
