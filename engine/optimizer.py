# engine/optimizer.py
from __future__ import annotations

import pandas as pd
from pypfopt import EfficientFrontier, EfficientSemivariance, objective_functions

from .constraints import build_stock_type_indices

_MIN_WEIGHT = 0.01  # 畸零單位門檻：低於此值視為零


def apply_min_weight_floor(
    w_series: pd.Series,
    asset_names: list[str],
    stock_type_idx: list[int],
    bond_type_idx: list[int],
    config: dict,
) -> pd.Series:
    """
    畸零單位後處理：
    1. 剔除 wi < MIN_WEIGHT 的資產
    2. 剩餘權重標準化（sum=1）
    3. 迭代修正上限違反（個別資產上限 & 股票總上限），多餘權重按比例分配給其他資產
    """
    upper = float(config["constraints"]["upper"])
    stock_limit = float(config["constraints"]["stock_type_limit"])
    bond_floor = float(config["constraints"].get("bond_type_floor", 0.0))
    asset_upper_map = config["constraints"].get("asset_upper", {})

    w = w_series.copy()

    # ── Step 1: 剔除畸零權重 ──────────────────────────────
    dropped = w[w < _MIN_WEIGHT].index.tolist()
    if dropped:
        print(f"[MinWeight] 剔除 {len(dropped)} 個畸零資產：{dropped}")
    w[w < _MIN_WEIGHT] = 0.0

    # ── Step 2: 標準化 ────────────────────────────────────
    w_sum = w.sum()
    if w_sum <= 0:
        print("[MinWeight][WARN] 剔除後無剩餘資產，返回原始權重")
        return w_series
    w = w / w_sum

    # ── Step 3: 迭代修正上限違反 ──────────────────────────
    tol = 1e-6
    for iteration in range(30):
        changed = False

        # (A) 個別資產上限
        for name in asset_names:
            limit = asset_upper_map.get(name, upper)
            if w[name] > limit + tol:
                excess = w[name] - limit
                w[name] = limit
                # 分配給其他尚未到達自身上限的資產（按比例）
                eligible = pd.Index([n for n in asset_names
                                     if n != name and w[n] < asset_upper_map.get(n, upper) - tol])
                eligible_sum = w[eligible].sum()
                if eligible_sum > 0:
                    w[eligible] += excess * w[eligible] / eligible_sum
                else:
                    # 所有資產都在上限，平均分配
                    others = pd.Index([n for n in asset_names if n != name])
                    w[others] += excess / len(others)
                print(f"[MinWeight] 壓回上限：{name} → {limit:.2%}，多餘 {excess:.4%} 重新分配")
                changed = True

        # (B) 股票類總上限
        stock_names = [asset_names[i] for i in stock_type_idx]
        stock_sum = w[stock_names].sum() if stock_names else 0.0
        if stock_sum > stock_limit + tol:
            excess = stock_sum - stock_limit
            # 按比例壓縮股票權重
            for name in stock_names:
                w[name] *= stock_limit / stock_sum
            # 釋出的權重分配給非股票資產
            non_stock = [n for n in asset_names if n not in stock_names]
            non_stock_sum = w[non_stock].sum()
            if non_stock_sum > 0:
                for name in non_stock:
                    w[name] += excess * w[name] / non_stock_sum
            print(f"[MinWeight] 股票總上限超過：{stock_sum:.4%} > {stock_limit:.2%}，已修正")
            changed = True

        if not changed:
            break

    return w


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

    # 債券下限（bond_list 總權重）
    bond_list = config["universe"]["bond_list"]
    bond_type_idx = build_stock_type_indices(asset_names, bond_list)
    bond_floor = float(config["constraints"].get("bond_type_floor", 0.0))

    obj = str(config["optimizer"]["objective"]).lower()

    # ========= Sharpe（保留） =========
    # ========= Sharpe（保留） =========
    if obj == "sharpe":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
        if bond_type_idx and bond_floor > 0:
            ef.add_constraint(lambda w: w[bond_type_idx].sum() >= bond_floor)

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
            if bond_type_idx and bond_floor > 0:
                ef.add_constraint(lambda w: w[bond_type_idx].sum() >= bond_floor)
            for name, limit in asset_upper_map.items():
                if name in asset_names:
                    idx = asset_names.index(name)
                    ef.add_constraint(lambda w, i=idx, l=limit: w[i] <= l)
            ef.add_objective(objective_functions.L2_reg, gamma=l2_gamma)
            ef.max_quadratic_utility(risk_aversion=risk_aversion)
        w = ef.clean_weights(rounding=6)
        
        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        return apply_min_weight_floor(w_series, asset_names, stock_type_idx, bond_type_idx, config)

    # ========= Utility（保留） =========
    if obj == "utility":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
        if bond_type_idx and bond_floor > 0:
            ef.add_constraint(lambda w: w[bond_type_idx].sum() >= bond_floor)

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
        
        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        return apply_min_weight_floor(w_series, asset_names, stock_type_idx, bond_type_idx, config)

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
        if bond_type_idx and bond_floor > 0:
            es.add_constraint(lambda w: w[bond_type_idx].sum() >= bond_floor)

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

        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        return apply_min_weight_floor(w_series, asset_names, stock_type_idx, bond_type_idx, config)

    # ========= Min Variance (New) =========
    if obj == "min_variance":
        ef = EfficientFrontier(mu, sigma, weight_bounds=(lower, upper))
        ef.add_constraint(lambda w: w[stock_type_idx].sum() <= stock_limit)
        if bond_type_idx and bond_floor > 0:
            ef.add_constraint(lambda w: w[bond_type_idx].sum() >= bond_floor)

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

        w_series = pd.Series(w).reindex(asset_names).fillna(0.0)
        return apply_min_weight_floor(w_series, asset_names, stock_type_idx, bond_type_idx, config)

    raise ValueError("optimizer.objective must be one of: sharpe | sortino | utility | min_variance")
