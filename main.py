from __future__ import annotations

import os
import pandas as pd
from pandas.tseries.offsets import MonthEnd

from engine.config import load_config
from engine.data_loader import load_all_data
from engine.return_model import build_expected_return
from engine.risk_model import build_covariance
from engine.optimizer import solve_weights
from engine.backtest import run_all_frequencies_monthly


# ===================== 核心 Pipeline =====================

def run_full_pipeline_markowitz(cfg: dict, data: dict):
    """
    正確邏輯（與 notebook 一致）：
    - 用 t-1 的資料算 mu / Sigma
    - 算出權重 w_t
    - 套用在 t 期的實際報酬
    """

    start_date = pd.to_datetime(cfg["dates"]["start_date"])
    bt_start   = pd.to_datetime(cfg["dates"]["backtest_start"])
    bt_end     = pd.to_datetime(cfg["dates"]["backtest_end"])
    lookback   = int(cfg["risk"]["lookback_months"])

    all_weights = []
    all_returns = []
    all_dates   = []

    print("▶ Building rolling Markowitz weights...")

    # 從「回測起始日前一個月」開始算權重
    cur = bt_start - MonthEnd(1)

    while cur < bt_end:
        # ==================================================
        # 1) 用 cur（t-1）以前的資料建模
        # ==================================================
        mu, hist_all, _ = build_expected_return(end=cur, config=cfg, data=data)

        # 風險 window（一定是過去資料）
        window = hist_all.iloc[-lookback:].copy()

        Sigma = build_covariance(
            window,
            lookback_months=lookback,
            cov_method=cfg["risk"]["cov_method"],
            annualize_factor=cfg["risk"]["annualize_factor"],
        )

        # ==================================================
        # 2) 解出「下一期」要用的權重
        # ==================================================
        w = solve_weights(mu=mu, sigma=Sigma, window=window, config=cfg)

        # ==================================================
        # 3) 取得「下一期」實際報酬
        # ==================================================
        next_date = cur + MonthEnd(1)

        # 用 data 中的 bond_industry + market 算實際報酬
        # 最乾淨方式：再呼叫一次 build_expected_return 拿 hist
        _, hist_next, _ = build_expected_return(end=next_date, config=cfg, data=data)

        r = hist_next.iloc[-1]  # 當期月報酬

        # ==================================================
        # 4) 紀錄
        # ==================================================
        all_dates.append(next_date)
        all_weights.append(w.values)
        all_returns.append(r.values)

        # 前進一期
        cur = next_date

    # 組成 DataFrame
    weights_df = pd.DataFrame(all_weights, index=all_dates, columns=mu.index)
    returns_df = pd.DataFrame(all_returns, index=all_dates, columns=mu.index)

    weights_df = weights_df.sort_index()
    returns_df = returns_df.sort_index()

    # 對齊回測區間
    weights_df = weights_df.loc[bt_start:bt_end]
    returns_df = returns_df.loc[bt_start:bt_end]

    # ==================================================
    # 5) 回測
    # ==================================================
    results = run_all_frequencies_monthly(
        returns_df,
        weights_df,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )

    return results, weights_df, returns_df


# ===================== UI 用 =====================

def run_ui_pipeline(cfg: dict):
    data = load_all_data(cfg)

    results_marko, weights_df, returns_df = run_full_pipeline_markowitz(cfg, data)

    # === 等權 ===
    n = returns_df.shape[1]
    w_eq = pd.DataFrame(1.0 / n, index=returns_df.index, columns=returns_df.columns)

    results_eq = run_all_frequencies_monthly(
        returns_df,
        w_eq,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )

    # === 60/40 benchmark ===
    bm = data["benchmark"].pct_change().dropna()
    bm = bm.reindex(returns_df.index).fillna(0.0)

    w_6040 = pd.DataFrame(
        [[0.6, 0.2, 0.2]] * len(bm),
        index=bm.index,
        columns=bm.columns,
    )

    results_6040 = run_all_frequencies_monthly(
        bm,
        w_6040,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )

    results_list = [results_marko, results_eq, results_6040]
    name_list = ["Markowitz", "Equal Weight", "60/40"]

    return results_list, name_list


# ===================== CLI 入口 =====================

def main():
    cfg = load_config("config.yaml")
    data = load_all_data(cfg)

    os.makedirs("outputs", exist_ok=True)

    results, weights_df, returns_df = run_full_pipeline_markowitz(cfg, data)

    # === 輸出檔案 ===
    weights_df.to_csv("outputs/weights.csv")
    returns_df.to_csv("outputs/returns.csv")

    # 取 Q 再平衡結果
    nav_q = results["Q"]["nav"]
    nav_q.to_csv("outputs/nav_Q.csv")

    # summary
    summary = []
    for rule, res in results.items():
        s = res["stats"].copy()
        s["rebalance_rule"] = rule
        summary.append(s)

    summary_df = pd.DataFrame(summary).set_index("rebalance_rule")
    summary_df.to_csv("outputs/summary.csv")

    print("✅ Done. Outputs in ./outputs")


if __name__ == "__main__":
    main()
