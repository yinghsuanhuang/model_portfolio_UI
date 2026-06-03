from __future__ import annotations

import os
import pandas as pd
from pandas.tseries.offsets import MonthEnd

from engine.config import load_config
from engine.data_loader import load_all_data, load_taa_data
from engine.return_model import build_expected_return
from engine.risk_model import build_covariance
from engine.optimizer import solve_weights
from engine.backtest import run_all_frequencies_monthly
from engine.taa import build_taa_weights


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



# ===================== TAA 疊加層 =====================

def build_taa_layer(
    cfg: dict,
    saa_weights_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    X: float,
    taa_data_path: str | None = None,
    nfp_threshold: float | None = None,
    pmi_threshold: float | None = None,
    last_period_override: dict | None = None,
):
    """
    在 SAA 月頻權重上疊加 TAA 調整，回測出 SAA+TAA 結果。
    回傳 (results_taa, taa_weights_df, signals_df, taa_data)。
    last_period_override: {"direction": int, "delta_x": float}，當期會議討論手動覆寫。
    """
    taa_data = load_taa_data(cfg, override_path=taa_data_path)

    taa_weights_df, signals_df = build_taa_weights(
        saa_weights_df, taa_data, cfg,
        X=X, nfp_threshold=nfp_threshold, pmi_threshold=pmi_threshold,
        last_period_override=last_period_override,
    )

    results_taa = run_all_frequencies_monthly(
        returns_df,
        taa_weights_df,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )

    return results_taa, taa_weights_df, signals_df, taa_data


# ===================== UI 用 =====================

def run_ui_pipeline(
    cfg: dict,
    data_path: str | None = None,
    taa_data_path: str | None = None,
    last_period_override: dict | None = None,
):
    data = load_all_data(cfg, override_path=data_path)

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

    # === TAA 疊加層（啟用且 X>0 時）===
    taa_info = None
    taa_cfg = cfg.get("taa", {})
    X = float(taa_cfg.get("current_X", 0.0))
    if taa_cfg.get("enabled", False) and X > 0:
        results_taa, taa_weights_df, signals_df, taa_data = build_taa_layer(
            cfg, weights_df, returns_df, X=X,
            taa_data_path=taa_data_path,
            nfp_threshold=taa_cfg.get("nfp_threshold"),
            pmi_threshold=taa_cfg.get("pmi_threshold"),
            last_period_override=last_period_override,
        )
        # 插在 Markowitz 後面，方便績效表/NAV 直接對比
        results_list.insert(1, results_taa)
        name_list.insert(1, "SAA + TAA")
        taa_info = {
            "results": results_taa,
            "weights_df": taa_weights_df,
            "saa_weights_df": weights_df,
            "signals_df": signals_df,
            "taa_data": taa_data,
            "X": X,
        }

    return results_list, name_list, weights_df, taa_info


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

    # ===================== TAA 疊加（CLI 驗證：積極型 X=10%）=====================
    if cfg.get("taa", {}).get("enabled", False):
        X = float(cfg["taa"]["profile_max_adjust"].get("積極型投資人", 0.10))
        print(f"\n▶ Building SAA+TAA layer (X={X:.0%}) ...")

        results_taa, taa_weights_df, signals_df, _taa_data = build_taa_layer(
            cfg, weights_df, returns_df, X=X,
        )

        taa_weights_df.to_csv("outputs/weights_taa.csv")
        signals_df.to_csv("outputs/taa_signals.csv")
        results_taa["Q"]["nav"].to_csv("outputs/nav_taa_Q.csv")

        s_saa = results["Q"]["stats"]
        s_taa = results_taa["Q"]["stats"]
        active = int((signals_df["delta_x"] != 0).sum())
        meets = int(signals_df["meeting_flag"].sum())
        print(f"  TAA 有調整月份：{active}/{len(signals_df)}；觸及會議討論：{meets}")
        print("  指標            SAA-only      SAA+TAA")
        for k in ["CAGR", "annualized_vol", "Sharpe", "Sortino", "max_drawdown", "Calmar"]:
            print(f"  {k:<15} {s_saa.get(k, float('nan')):>10.4f}  {s_taa.get(k, float('nan')):>10.4f}")

    print("✅ Done. Outputs in ./outputs")


if __name__ == "__main__":
    main()
