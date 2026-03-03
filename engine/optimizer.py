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
    # ========= Sharpe（保留） =========
    if obj == "sharpe":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)

        # --- New: Individual Asset Constraints ---
        asset_upper_map = config["constraints"].get("asset_upper", {})
        for name, limit in asset_upper_map.items():
            if name in asset_names:
                idx = asset_names.index(name)
                print(f"[DEBUG][Sharpe] Adding constraint: {name} (idx={idx}) <= {limit}")
                ef.add_constraint(lambda w, i=idx, l=limit: w[i] <= l)

        ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
        try:
            ef.max_sharpe()
        except Exception as e:
            print(f"[WARN][Sharpe] max_sharpe failed ({e}), falling back to max_quadratic_utility")
            # Rebuild EF since the failed solve may have corrupted state
            ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
            ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
            for name, limit in asset_upper_map.items():
                if name in asset_names:
                    idx = asset_names.index(name)
                    ef.add_constraint(lambda w, i=idx, l=limit: w[i] <= l)
            ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
            ef.max_quadratic_utility(risk_aversion=risk_aversion)
        w = ef.clean_weights(rounding=6)
        
        # Double Check constraints
        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        for name, limit in asset_upper_map.items():
            if name in w_series.index:
                val = w_series[name]
                if val > limit + 0.001:
                    print(f"[DEBUG][Sharpe] Constraint violated after clean: {name} = {val:.4f} > {limit}")
                    w_series[name] = limit
                    other_sum = w_series.drop(name).sum()
                    if other_sum > 0:
                        w_series[w_series.index != name] *= (1.0 - limit) / other_sum
        return w_series

    # ========= Utility（保留） =========
    if obj == "utility":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)

        # --- New: Individual Asset Constraints ---
        asset_upper_map = config["constraints"].get("asset_upper", {})
        for name, limit in asset_upper_map.items():
            if name in asset_names:
                idx = asset_names.index(name)
                print(f"[DEBUG][Utility] Adding constraint: {name} (idx={idx}) <= {limit}")
                ef.add_constraint(lambda w, i=idx, l=limit: w[i] <= l)

        ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
        ef.max_quadratic_utility(risk_aversion=risk_aversion)
        w = ef.clean_weights(rounding=6)
        
        # Double Check constraints
        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        for name, limit in asset_upper_map.items():
            if name in w_series.index:
                val = w_series[name]
                if val > limit + 0.001:
                    print(f"[DEBUG][Utility] Constraint violated after clean: {name} = {val:.4f} > {limit}")
                    w_series[name] = limit
                    other_sum = w_series.drop(name).sum()
                    if other_sum > 0:
                        w_series[w_series.index != name] *= (1.0 - limit) / other_sum
        return w_series

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
        
        # --- New: Individual Asset Constraints ---
        # config["constraints"]["asset_upper"] = {"Asset_Name": 0.2, ...}
        asset_upper_map = config["constraints"].get("asset_upper", {})
        for name, limit in asset_upper_map.items():
            if name in asset_names:
                idx = asset_names.index(name)
                # constraint: w[idx] <= limit
                # Note: creating closure properly in loop
                print(f"[DEBUG] Adding constraint: {name} (idx={idx}) <= {limit}")
                es.add_constraint(lambda w, i=idx, l=limit: w[i] <= l)
            else:
                print(f"[DEBUG] Warning: Constraint asset {name} not found in {asset_names}")

        es.add_objective(objective_functions.L2_reg, gamma=l2_gamma)

        # ✅ notebook 對齊：固定用 max_quadratic_utility(2)
        es.max_quadratic_utility(risk_aversion=risk_aversion)

        # 這裡用 rounding=6 確實可能導致 normalization 後比例跑掉
        # 試著先不 round，或者手動檢查
        # w = es.clean_weights(rounding=6)
        w_raw = es.weights
        # clean_weights 做的事情主要是 set small to 0 and normalize
        # 我們自己做簡單的清理，確保不違反 constraint
        
        # 使用 pypfopt 的 clean_weights 但稍微小心
        w = es.clean_weights(rounding=6)
        
        # Double Check constraints
        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        for name, limit in asset_upper_map.items():
            if name in w_series.index:
                val = w_series[name]
                if val > limit + 0.001: # 容忍 0.1% 誤差
                    print(f"[DEBUG] Constraint violated after clean: {name} = {val:.4f} > {limit}")
                    # 強制修正 (很粗暴但有效)
                    diff = val - limit
                    w_series[name] = limit
                    # 把多出來的分配給其他最大的資產 (或 simply normalize)
                    # 這裡簡單處理：除了該資產外，normalize 到 (1-limit)
                    other_sum = w_series.drop(name).sum()
                    if other_sum > 0:
                        w_series[w_series.index != name] *= (1.0 - limit) / other_sum
        
        return w_series

    # ========= Min Variance (New) =========
    if obj == "min_variance":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)

        # --- Individual Asset Constraints ---
        asset_upper_map = config["constraints"].get("asset_upper", {})
        for name, limit in asset_upper_map.items():
            if name in asset_names:
                idx = asset_names.index(name)
                print(f"[DEBUG][MinVar] Adding constraint: {name} (idx={idx}) <= {limit}")
                ef.add_constraint(lambda w, i=idx, l=limit: w[i] <= l)

        # ef.min_volatility() handles L2 reg internally if we passed solver params, 
        # but pypfopt usually adds L2 regularisation via add_objective before optimization if desired.
        # min_volatility() doesn't seemingly take gamma in standard usage like max_sharpe does via add_objective(L2_reg),
        # but let's follow the standard pattern:
        ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
        
        ef.min_volatility()
        w = ef.clean_weights(rounding=6)
        
        # Double Check constraints
        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        for name, limit in asset_upper_map.items():
            if name in w_series.index:
                val = w_series[name]
                if val > limit + 0.001:
                    print(f"[DEBUG][MinVar] Constraint violated after clean: {name} = {val:.4f} > {limit}")
                    w_series[name] = limit
                    other_sum = w_series.drop(name).sum()
                    if other_sum > 0:
                        w_series[w_series.index != name] *= (1.0 - limit) / other_sum
        return w_series

    raise ValueError("optimizer.objective must be one of: sharpe | sortino | utility | min_variance")
