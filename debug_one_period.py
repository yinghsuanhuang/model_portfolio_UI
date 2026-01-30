# debug_one_period.py
from __future__ import annotations
import pandas as pd

from engine.config import load_config
from engine.data_loader import load_all_data
from engine.return_model import build_expected_return
from engine.risk_model import build_covariance
from engine.optimizer import solve_weights
from engine.constraints import build_stock_type_indices

# =========================
# 設定要檢查的日期（notebook 第一筆）
# =========================
TARGET_DATE = pd.to_datetime("2012-01-31")

def main():
    cfg = load_config("config.yaml")
    data = load_all_data(cfg)

    lookback = int(cfg["risk"]["lookback_months"])

    print("==============================================")
    print("DEBUG DATE =", TARGET_DATE)
    print("==============================================")

    # === 1) 建立 μ 與歷史報酬 ===
    mu, hist_all, _ = build_expected_return(end=TARGET_DATE, config=cfg, data=data)

    print("\n==================== MU (Expected Return) ====================")
    print(mu.sort_values(ascending=False))

    # === 2) 建立 window ===
    window = hist_all.iloc[-lookback:].copy()

    print("\n==================== WINDOW INFO ====================")
    print("window start =", window.index[0])
    print("window end   =", window.index[-1])
    print("window shape =", window.shape)

    print("\nWINDOW HEAD:")
    print(window.head())

    print("\nWINDOW TAIL:")
    print(window.tail())

    # === 3) 建立 Sigma ===
    Sigma = build_covariance(
        window,
        lookback_months=lookback,
        cov_method=cfg["risk"]["cov_method"],
        annualize_factor=cfg["risk"]["annualize_factor"],
    )

    print("\n==================== SIGMA (diag = variance) ====================")
    print(pd.Series(Sigma.values.diagonal(), index=Sigma.index))

    print("\n==================== SIGMA (vol approx) ====================")
    print(pd.Series((Sigma.values.diagonal() ** 0.5), index=Sigma.index))

    # === 4) 資產順序 ===
    asset_names = list(mu.index)

    print("\n==================== ASSET ORDER ====================")
    for i, a in enumerate(asset_names):
        print(f"{i:2d}  {a}")

    # === 5) 檢查 stock type constraint ===
    market_list = cfg["universe"]["market_list"]
    industry_list = cfg["universe"]["industry_list"]

    stock_type = [m.replace(" ", "_") for m in market_list] + industry_list
    stock_type_idx = build_stock_type_indices(asset_names, stock_type)

    print("\n==================== STOCK TYPE LIST (FROM CONFIG) ====================")
    print(stock_type)

    print("\n==================== STOCK TYPE IDX ASSETS ====================")
    print([asset_names[i] for i in stock_type_idx])

    # === 6) 解權重 ===
    print("\n==================== SOLVING WEIGHTS ====================")

    w = solve_weights(mu, Sigma, window, cfg)

    print("\n==================== WEIGHTS ====================")
    print(w)
    print("SUM =", w.sum())


    print("\n==================== FILES SAVED ====================")
    print("debug_mu_2012_01.csv")
    print("debug_window_2012_01.csv")
    print("debug_sigma_2012_01.csv")
    print("debug_weights_2012_01.csv")

    print("\n✅ DEBUG DONE")

if __name__ == "__main__":
    main()
