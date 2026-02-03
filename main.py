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

    bt_start   = pd.to_datetime(cfg["dates"]["backtest_start"])
    bt_end     = pd.to_datetime(cfg["dates"]["backtest_end"])
    lookback   = int(cfg["risk"]["lookback_months"])

    all_weights = []
    all_returns = []
    all_dates   = []

    print("▶ Building Markowitz weights (Notebook time-aligned)...")

    # 從 bt_start 的「前一個月」開始建模
    cur = bt_start - MonthEnd(1)

    while True:
        next_date = cur + MonthEnd(1)

        if next_date > bt_end:
            break

        # ==================================================
        # 1) 用「cur」的資料建模（t-1 資訊）
        # ==================================================
        mu, hist_all, _ = build_expected_return(end=cur, config=cfg, data=data)

        window = hist_all.iloc[-lookback:].copy()

        Sigma = build_covariance(
            window,
            lookback_months=lookback,
            cov_method=cfg["risk"]["cov_method"],
            annualize_factor=cfg["risk"]["annualize_factor"],
        )

        # ==================================================
        # 2) 解出「下個月要用」的權重 w(t)
        # ==================================================
        w = solve_weights(mu=mu, sigma=Sigma, window=window, config=cfg)

        # ==================================================
        # 3) 取得「next_date」的實際月報酬 r(t)
        # ==================================================
        _, hist_next, _ = build_expected_return(end=next_date, config=cfg, data=data)
        r_next = hist_next.iloc[-1]

        # ==================================================
        # 4) 記錄（權重與報酬都屬於 next_date）
        # ==================================================
        all_dates.append(next_date)
        all_weights.append(w.values)
        all_returns.append(r_next.values)

        # 前進一個月
        cur = next_date

    weights_df = pd.DataFrame(all_weights, index=all_dates, columns=mu.index)
    returns_df = pd.DataFrame(all_returns, index=all_dates, columns=mu.index)

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
