from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .data_loader import load_market_sheet
from .utils import period_returns


def _asof_last_row(df: pd.DataFrame, end: pd.Timestamp) -> pd.Series:
    """拿 <= end 的最後一筆 row，避免 end 不在 index 造成 KeyError，也避免偷看未來。"""
    df2 = df.loc[:end]
    if df2.empty:
        raise ValueError(f"No data available on or before end={end}")
    return df2.iloc[-1]


def _compute_5y_metrics(
    df: pd.DataFrame,
    *,
    end: pd.Timestamp,
    rolling_years: int,
    min_years: float = 3.0,   # 資料太短時，growth 很容易爆；用這個保護一下
) -> tuple[float, float]:
    """
    回傳：
    - growth_rate_annualized
    - avg_pe
    """
    eps_col = "近12個月每股盈餘  (R2)"
    price_col = "Price"

    start = end - pd.DateOffset(years=rolling_years)
    window = df.loc[start:end].copy()
    if window.empty:
        raise ValueError(f"5Y window empty: start={start}, end={end}")

    eps = window[eps_col].replace([np.inf, -np.inf], np.nan).dropna()
    if len(eps) < 2:
        # EPS 資料不足就回傳 0 成長、PE 用當期（或整段平均）
        row_end = _asof_last_row(window, end)
        pe = (window[price_col] / window[eps_col]).replace([np.inf, -np.inf], np.nan).dropna()
        avg_pe = float(pe.mean()) if not pe.empty else float(row_end[price_col] / max(row_end[eps_col], 1e-9))
        return 0.0, float(avg_pe)

    eps_start, eps_end = float(eps.iloc[0]), float(eps.iloc[-1])
    actual_years = (eps.index[-1] - eps.index[0]).days / 365.25

    # --- growth：對齊 notebook 的概念，但加上資料太短保護 ---
    if actual_years <= 0:
        growth_rate = 0.0
    else:
        if eps_start > 0 and eps_end > 0 and actual_years >= min_years:
            growth_rate = (eps_end / eps_start) ** (1 / actual_years) - 1
        else:
            # 資料太短 / 有負值：用算術近似，避免爆表
            growth_5y = (eps_end - eps_start) / (eps_start if eps_start != 0 else 1e-9)
            growth_rate = growth_5y / max(actual_years, 1e-9)

    pe = (window[price_col] / window[eps_col]).replace([np.inf, -np.inf], np.nan).dropna()
    avg_pe = float(pe.mean()) if not pe.empty else np.nan

    return float(growth_rate), float(avg_pe)


def build_expected_return(end: pd.Timestamp, config: dict, data: dict):
    """
    回傳（3 個）：
    - mu : Series (index = asset names)         # 年化期望報酬（對齊 notebook）
    - hist_returns_all : DataFrame              # 月報酬序列（給回測 & risk 用）
    - window_for_risk : DataFrame               # 已切 lookback + 補值（只給風險模型）
    """
    expected_path = data["expected_path"]
    df2_raw = data["bond_industry"]

    market_list = config["universe"]["market_list"]
    industry_list = config["universe"]["industry_list"]
    bond_list = config["universe"]["bond_list"]

    lookback = int(config["risk"]["lookback_months"])
    rolling_years = int(config["return_model"]["rolling_years"])
    method = config["project"]["price_return_method"]

    # notebook 的 start_date 概念：只用來算「報酬預測」
    start_date = pd.to_datetime(config["dates"]["start_date"])

    asset_list: list[str] = []
    exp_list: list[float] = []
    hist_df = pd.DataFrame()

    # ========= 股票（對齊 notebook：growth + div + valuation） =========
    for m in market_list:
        name = m.replace(" ", "_")
        sheet = m.upper()

        df_raw = load_market_sheet(expected_path, sheet_name=sheet)

        # (A) 給 μ 用：只切 start_date:end
        df_mu = df_raw.loc[start_date:end].copy()
        if df_mu.empty:
            raise ValueError(f"Equity sheet {sheet} has no data in [{start_date}, {end}]")

        row_end = _asof_last_row(df_mu, end)

        growth_rate, avg_pe = _compute_5y_metrics(
            df_mu, end=row_end.name, rolling_years=rolling_years
        )

        # div：用 start:end 平均
        div_y = float(df_mu["股利率12個月殖利率-毛額  (R1)"].mean()) * 0.01

        # valuation：用當期 row_end
        best_eps = float(row_end["BEst每股盈餘  (L2)"])
        price = float(row_end["Price"])
        val_adj = (best_eps * avg_pe - price) / price if price != 0 else 0.0

        exp_ret = float(growth_rate + div_y + val_adj)

        # (B) 給風險用：用「完整歷史」
        df_risk = df_raw.loc[:row_end.name].copy()

        r = period_returns(df_risk["Price"], method=method)
        r = r.loc[r.index <= row_end.name]
        r.name = name

        asset_list.append(name)
        exp_list.append(exp_ret)
        hist_df = pd.concat([hist_df, r], axis=1)

    # ========= 債券（對齊 notebook：E_ytm = ytm - dur*(forecast - y10)） =========
    # μ 用：start_date:end
    df2_mu = df2_raw.loc[start_date:end].copy()
    if df2_mu.empty:
        raise ValueError(f"Bond/Industry sheet has no data in [{start_date}, {end}]")

    row2_end = _asof_last_row(df2_mu, end)

    for b in bond_list:
        ytm = float(row2_end[f"{b}YTM"]) * 0.01
        dur = float(row2_end[f"{b}Dur"]) * 0.01
        forecast = float(row2_end["債券殖利率預估"]) * 0.01
        y10 = float(row2_end["10年期公債殖利率"]) * 0.01

        exp_ret = float(ytm - dur * (forecast - y10))

        # 風險用：完整歷史
        r = df2_raw.loc[:row2_end.name, b].copy()
        r.name = b

        asset_list.append(b)
        exp_list.append(exp_ret)
        hist_df = pd.concat([hist_df, r], axis=1)

    # ========= 產業（CAPM beta；對齊 notebook） =========
    spx_name = market_list[0].replace(" ", "_")
    spx_exp = exp_list[asset_list.index(spx_name)]  # 已是年化

    for ind in industry_list:
        start_beta = row2_end.name - pd.DateOffset(years=rolling_years)
        window = df2_raw.loc[start_beta:row2_end.name].copy()
        if window.empty:
            raise ValueError(f"Industry beta window empty for {ind} at {row2_end.name}")

        rf_month = (window["10年期公債殖利率"] / 100.0) * 30.0 / 365.0
        y = (window[ind] - rf_month).dropna()
        x = (window["標普500"] - rf_month).reindex(y.index)

        X = sm.add_constant(x)
        res = sm.OLS(y, X).fit()
        beta = float(res.params.drop("const").iloc[0])

        exp_ret = float(row2_end["債券殖利率預估"] / 100.0 + spx_exp * beta)

        # 風險用：完整歷史
        r = df2_raw.loc[:row2_end.name, ind].copy()
        r.name = ind

        asset_list.append(ind)
        exp_list.append(exp_ret)
        hist_df = pd.concat([hist_df, r], axis=1)

    # ========= 組裝 =========
    mu = pd.Series(exp_list, index=asset_list)
    hist_df = hist_df.sort_index()

    # 只在這裡切「風險視窗」+ 補值
    window_for_risk = hist_df.iloc[-lookback:].copy()
    window_for_risk = window_for_risk.ffill().bfill()

    return mu, hist_df, window_for_risk
