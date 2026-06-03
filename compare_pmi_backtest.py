#!/usr/bin/env python3
"""
PMI Proxy 比較回測
==================
比較 CFNAI 作為 PMI 代理前後，TAA 策略績效的差異。

Scenario A : SAA only（無 TAA，X=0）
Scenario B : TAA + CFNAI PMI proxy（2010-2026 全段，現況）
Scenario C : TAA without PMI supplement（PMI 僅用 Excel 資料；2023-05 前 pmi_score=0）

用途：驗證 CFNAI 代理是否提升或惡化信號品質，以及延長歷史是否有統計意義。
"""
from __future__ import annotations

import copy
import numpy as np
import pandas as pd
from pathlib import Path

from engine.config import load_config
from engine.data_loader import load_all_data, load_taa_data
from engine.return_model import build_expected_return
from engine.risk_model import build_covariance
from engine.optimizer import solve_weights
from engine.backtest import run_all_frequencies_monthly
from engine.taa import build_taa_weights, compute_factor_scores
from pandas.tseries.offsets import MonthEnd


# ── config ──────────────────────────────────────────────
REBALANCE_RULE = "Q"
X_PROFILE = 0.10   # 積極型投資人最大調整幅度


# ── 1. SAA pipeline ──────────────────────────────────────
def build_saa(cfg: dict, data: dict):
    bt_start = pd.to_datetime(cfg["dates"]["backtest_start"])
    bt_end   = pd.to_datetime(cfg["dates"]["backtest_end"])
    lookback = int(cfg["risk"]["lookback_months"])

    all_weights, all_returns, all_dates = [], [], []
    cur = bt_start - MonthEnd(1)

    while True:
        next_date = cur + MonthEnd(1)
        if next_date > bt_end:
            break
        mu, hist_all, _ = build_expected_return(end=cur, config=cfg, data=data)
        window = hist_all.iloc[-lookback:].copy()
        Sigma = build_covariance(window, lookback_months=lookback,
                                 cov_method=cfg["risk"]["cov_method"],
                                 annualize_factor=cfg["risk"]["annualize_factor"])
        w = solve_weights(mu=mu, sigma=Sigma, window=window, config=cfg)
        _, hist_next, _ = build_expected_return(end=next_date, config=cfg, data=data)
        r_next = hist_next.iloc[-1]
        all_dates.append(next_date)
        all_weights.append(w.values)
        all_returns.append(r_next.values)
        cur = next_date

    weights_df = pd.DataFrame(all_weights, index=all_dates, columns=mu.index)
    returns_df = pd.DataFrame(all_returns, index=all_dates, columns=mu.index)
    return weights_df, returns_df


# ── 2. 年度報酬工具 ──────────────────────────────────────
def annual_returns(nav: pd.Series) -> pd.Series:
    r = nav.resample("YE").last().pct_change().dropna()
    r.index = r.index.year
    return r.rename("return")


# ── 3. 訊號比較工具 ──────────────────────────────────────
def signals_summary(signals_df: pd.DataFrame) -> dict:
    total = len(signals_df)
    active = int((signals_df["delta_x"] != 0).sum())
    add_months = int((signals_df["delta_x"] > 0).sum())
    reduce_months = int((signals_df["delta_x"] < 0).sum())
    neutral = total - active
    return dict(total=total, active=active, add=add_months, reduce=reduce_months, neutral=neutral)


# ── 4. CFNAI 信號品質驗證 ──────────────────────────────────
def validate_cfnai_signal(signals_b: pd.DataFrame, returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    驗證 CFNAI PMI 代理的信號品質：
      pmi_score 方向 vs. 下個月 SPX（或投組）實際報酬
    """
    spx_col = next((c for c in returns_df.columns if "SPX" in c.upper()), None)
    if spx_col is None:
        return pd.DataFrame()

    spx_ret = returns_df[spx_col].rename("spx_return")
    sig_pmi = signals_b["pmi_score"].copy()

    df = pd.concat([sig_pmi, spx_ret.shift(-1)], axis=1).dropna()
    df.columns = ["pmi_score", "next_spx"]

    table_rows = []
    for score in [1, 0, -1]:
        sub = df[df["pmi_score"] == score]["next_spx"]
        if len(sub) == 0:
            continue
        table_rows.append({
            "pmi_score": score,
            "n_months": len(sub),
            "avg_next_spx (ann%)": round(sub.mean() * 12 * 100, 2),
            "hit_ratio": round((sub > 0).mean(), 3),
        })

    return pd.DataFrame(table_rows)


# ── Main ─────────────────────────────────────────────────
def main():
    print("═" * 60)
    print("PMI Proxy 比較回測（SAA-only vs TAA+CFNAI vs TAA+Excel-only PMI）")
    print("═" * 60)

    cfg = load_config("config.yaml")
    data = load_all_data(cfg)

    # === Step 1: SAA pipeline ===
    print("\n▶ 建構 SAA 權重…（需幾分鐘）")
    weights_df, returns_df = build_saa(cfg, data)

    results_saa = run_all_frequencies_monthly(
        returns_df, weights_df,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )
    nav_saa = results_saa[REBALANCE_RULE]["nav"]
    stats_saa = results_saa[REBALANCE_RULE]["stats"]

    # === Step 2: TAA with CFNAI (Scenario B) ===
    print("▶ Scenario B：TAA + CFNAI PMI 代理…")
    taa_data_b = load_taa_data(cfg)   # 含 CSV 補充（CFNAI）

    taa_weights_b, signals_b = build_taa_weights(
        weights_df, taa_data_b, cfg,
        X=X_PROFILE,
        nfp_threshold=float(cfg["taa"].get("nfp_threshold", 50)),
        pmi_threshold=float(cfg["taa"].get("pmi_threshold", 0.0)),
    )
    results_b = run_all_frequencies_monthly(
        returns_df, taa_weights_b,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )
    nav_b = results_b[REBALANCE_RULE]["nav"]
    stats_b = results_b[REBALANCE_RULE]["stats"]

    # === Step 3: TAA with Excel-only PMI (Scenario C) ===
    print("▶ Scenario C：TAA，PMI 僅用 Excel 資料（2023-05 前 pmi_score=0）…")
    taa_data_c = copy.deepcopy(taa_data_b)
    excel_pmi_start = pd.Timestamp("2023-05-31")
    taa_data_c["macro"].loc[
        taa_data_c["macro"].index < excel_pmi_start, "pmi"
    ] = np.nan

    taa_weights_c, signals_c = build_taa_weights(
        weights_df, taa_data_c, cfg,
        X=X_PROFILE,
        nfp_threshold=float(cfg["taa"].get("nfp_threshold", 50)),
        pmi_threshold=float(cfg["taa"].get("pmi_threshold", 0.0)),
    )
    results_c = run_all_frequencies_monthly(
        returns_df, taa_weights_c,
        starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )
    nav_c = results_c[REBALANCE_RULE]["nav"]
    stats_c = results_c[REBALANCE_RULE]["stats"]

    # ── 打印結果 ──────────────────────────────────────────
    KEYS = ["CAGR", "annualized_vol", "Sharpe", "Sortino", "max_drawdown", "Calmar"]

    print(f"\n{'─'*60}")
    print(f"  整體績效比較（再平衡規則：{REBALANCE_RULE}，X={X_PROFILE:.0%}）")
    print(f"{'─'*60}")
    header = f"{'指標':<18} {'SAA-only':>12} {'TAA+CFNAI':>12} {'TAA+ExcelPMI':>14}"
    print(header)
    print("─" * 60)
    for k in KEYS:
        a = stats_saa.get(k, float("nan"))
        b = stats_b.get(k, float("nan"))
        c = stats_c.get(k, float("nan"))
        label = "%" if k in ["CAGR", "annualized_vol", "max_drawdown"] else ""
        mult = 100 if label == "%" else 1
        print(f"  {k:<16} {a*mult:>11.2f}{label}  {b*mult:>11.2f}{label}  {c*mult:>13.2f}{label}")

    # ── 年度報酬比較 ──────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  年度報酬比較（%）")
    print(f"{'─'*60}")
    ar_saa = annual_returns(nav_saa) * 100
    ar_b   = annual_returns(nav_b)   * 100
    ar_c   = annual_returns(nav_c)   * 100

    years = ar_saa.index.union(ar_b.index).union(ar_c.index)
    print(f"  {'年份':<8} {'SAA-only':>10} {'TAA+CFNAI':>12} {'TAA+ExcelPMI':>14} {'B-A':>8} {'C-A':>8}")
    print("─" * 60)
    for yr in years:
        a  = ar_saa.get(yr, float("nan"))
        b  = ar_b.get(yr, float("nan"))
        c  = ar_c.get(yr, float("nan"))
        ba = b - a if not np.isnan(b) and not np.isnan(a) else float("nan")
        ca = c - a if not np.isnan(c) and not np.isnan(a) else float("nan")
        print(f"  {yr:<8} {a:>9.2f}%  {b:>11.2f}%  {c:>13.2f}%  {ba:>+7.2f}%  {ca:>+7.2f}%")

    # ── 訊號分佈比較 ──────────────────────────────────────
    print(f"\n{'─'*60}")
    print("  TAA 訊號分佈比較")
    print(f"{'─'*60}")
    sb = signals_summary(signals_b)
    sc = signals_summary(signals_c)
    print(f"  {'指標':<20} {'TAA+CFNAI':>12} {'TAA+ExcelPMI':>14}")
    for k, vb, vc in [
        ("Total months", sb["total"], sc["total"]),
        ("Active months", sb["active"], sc["active"]),
        ("加碼月份 (delta>0)", sb["add"], sc["add"]),
        ("減碼月份 (delta<0)", sb["reduce"], sc["reduce"]),
        ("中立月份", sb["neutral"], sc["neutral"]),
    ]:
        print(f"  {k:<20} {vb:>12}   {vc:>14}")

    # ── PMI 訊號一致性（B vs C 的差異月份）────────────────
    pmi_b = signals_b["pmi_score"]
    pmi_c = signals_c["pmi_score"]
    diff = (pmi_b != pmi_c)
    print(f"\n  Scenario B vs C pmi_score 差異月份數：{diff.sum()} / {len(diff)}")
    if diff.sum() > 0:
        print("  差異月份（前 15 筆）：")
        diff_dates = diff[diff].index[:15]
        compare_pmi = pd.concat([pmi_b[diff_dates], pmi_c[diff_dates]], axis=1)
        compare_pmi.columns = ["CFNAI_score", "Excel_score"]
        print(compare_pmi.to_string(index=True))

    # ── CFNAI 信號品質驗證 ────────────────────────────────
    print(f"\n{'─'*60}")
    print("  CFNAI PMI 信號品質：pmi_score 方向 vs. 下月 SPX 實際報酬")
    print(f"{'─'*60}")
    quality_df = validate_cfnai_signal(signals_b, returns_df)
    if not quality_df.empty:
        print(quality_df.to_string(index=False))
    else:
        print("  （無 SPX 欄位，跳過）")

    # ── macro_score 分佈 ──────────────────────────────────
    print(f"\n{'─'*60}")
    print("  TAA+CFNAI：macro_score 分佈（整體方向強度）")
    print(f"{'─'*60}")
    score_dist = signals_b["macro_score"].value_counts().sort_index()
    for score, cnt in score_dist.items():
        bar = "█" * int(cnt / len(signals_b) * 40)
        pct = cnt / len(signals_b) * 100
        print(f"  score {score:+d}:  {cnt:>4} 月 ({pct:5.1f}%) {bar}")

    print(f"\n{'═'*60}")
    print("比較完成。")
    print(f"  SAA-only 最終 NAV:       {nav_saa.iloc[-1]:.4f}")
    print(f"  TAA+CFNAI 最終 NAV:      {nav_b.iloc[-1]:.4f}")
    print(f"  TAA+ExcelPMI 最終 NAV:   {nav_c.iloc[-1]:.4f}")
    print(f"{'═'*60}")


if __name__ == "__main__":
    main()
