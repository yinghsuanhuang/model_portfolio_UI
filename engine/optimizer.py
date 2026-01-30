# engine/optimizer.py
from __future__ import annotations

import pandas as pd
from pypfopt import EfficientFrontier, EfficientSemivariance, objective_functions

from .constraints import build_stock_type_indices


def solve_weights(
    mu: pd.Series,
    sigma: pd.DataFrame,
    window: pd.DataFrame,
    config: dict
) -> pd.Series:
    """
    - mu: 各資產期望報酬（Series）
    - sigma: 共變異矩陣（DataFrame）
    - window: 過去報酬視窗（Sortino 用）
    - config: 全域設定
    """
    lower = float(config["constraints"]["lower"])
    upper = float(config["constraints"]["upper"])
    stock_limit = float(config["constraints"]["stock_type_limit"])

    # notebook：gamma=0.1（L2_reg）
    l2_gamma = float(config["optimizer"].get("l2_gamma", 0.1))

    # notebook：Sortino benchmark = MAR（通常 0）
    mar = float(config["risk"].get("mar", 0.0))

    # notebook：Sortino 用 max_quadratic_utility(2)
    risk_aversion = float(config["optimizer"].get("risk_aversion", 2.0))

    asset_names = list(mu.index)

    # 股票類型限制（市場 + 產業）
    market_list = config["universe"]["market_list"]
    industry_list = config["universe"]["industry_list"]
    stock_type = [m.replace(" ", "_") for m in market_list] + industry_list
    stock_type_idx = build_stock_type_indices(asset_names, stock_type)

    obj = str(config["optimizer"]["objective"]).lower()

    # ========= Sharpe（保留） =========
    if obj == "sharpe":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
        ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
        ef.max_sharpe()
        w = ef.clean_weights(rounding=6)
        return pd.Series(w).reindex(asset_names).fillna(0.0)

    # ========= Utility（保留） =========
    if obj == "utility":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
        ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
        ef.max_quadratic_utility(risk_aversion=risk_aversion)
        w = ef.clean_weights(rounding=6)
        return pd.Series(w).reindex(asset_names).fillna(0.0)

    # ========= Sortino（正式版：max_quadratic_utility(2)） =========
    if obj == "sortino":
        es = EfficientSemivariance(
            mu,
            window,
            frequency=12,
            benchmark=mar,
            weight_bounds=(lower, upper),
        )
        es.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
        es.add_objective(objective_functions.L2_reg, gamma=l2_gamma)

        # ✅ notebook 對齊：固定用 max_quadratic_utility(2)
        es.max_quadratic_utility(risk_aversion=risk_aversion)

        w = es.clean_weights(rounding=6)
        return pd.Series(w).reindex(asset_names).fillna(0.0)

    raise ValueError("optimizer.objective must be one of: sharpe | sortino | utility")
