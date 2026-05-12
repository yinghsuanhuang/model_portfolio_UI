"""
Run backtests for Aggressive, Growth, Conservative profiles
under their default settings and compare metrics.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import copy
import pandas as pd
from engine.config import load_config
from engine.data_loader import load_all_data
from main import run_full_pipeline_markowitz

base_cfg = load_config("config.yaml")
data = load_all_data(base_cfg)

profiles = {
    "積極型投資人": {
        "constraints.upper": 0.5,
        "constraints.stock_type_limit": 0.7,
        "constraints.asset_upper": {},
        "optimizer.objective": "sortino",
        # full universe (no overrides)
    },
    "成長型投資人": {
        "constraints.upper": 0.2,
        "constraints.stock_type_limit": 0.55,
        "constraints.asset_upper": {},
        "optimizer.objective": "sharpe",
        # full universe
    },
    "保守型投資人": {
        "constraints.upper": 1.0,
        "constraints.stock_type_limit": 0.0,
        "constraints.asset_upper": {"非投資級債": 0.2},
        "optimizer.objective": "min_variance",
        "universe.market_list": [],
        "universe.industry_list": [],
        "universe.bond_list": ["投資級債", "非投資級債"],
    },
}

all_stats = []

for name, overrides in profiles.items():
    print(f"\n{'='*60}")
    print(f"  Profile: {name}")
    print(f"{'='*60}")
    
    cfg = copy.deepcopy(base_cfg)
    
    # Apply overrides
    for key, val in overrides.items():
        parts = key.split(".")
        d = cfg
        for p in parts[:-1]:
            d = d[p]
        d[parts[-1]] = val
    
    print(f"  Objective: {cfg['optimizer']['objective']}")
    print(f"  Upper: {cfg['constraints']['upper']}")
    print(f"  Stock Limit: {cfg['constraints']['stock_type_limit']}")
    print(f"  Asset Upper: {cfg['constraints'].get('asset_upper', {})}")
    print(f"  Market List: {cfg['universe']['market_list']}")
    print(f"  Bond List: {cfg['universe']['bond_list']}")
    
    try:
        results, weights_df, returns_df = run_full_pipeline_markowitz(cfg, data)
        
        # Use Q rebalance stats
        stats = results["Q"]["stats"]
        stats["profile"] = name
        all_stats.append(stats)
        
        # Show latest weights
        last_w = weights_df.iloc[-1]
        print(f"\n  Latest Weights:")
        for asset, w in last_w.items():
            if w > 0.001:
                print(f"    {asset}: {w:.1%}")
        
        print(f"\n  Performance (Q Rebalance):")
        print(f"    CAGR:      {stats['CAGR']:.2%}")
        print(f"    Vol:       {stats['annualized_vol']:.2%}")
        print(f"    Sharpe:    {stats['Sharpe']:.3f}")
        print(f"    Sortino:   {stats['Sortino']:.3f}")
        print(f"    Max DD:    {stats['max_drawdown']:.2%}")
        print(f"    Calmar:    {stats['Calmar']:.3f}")
        
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

# Summary table
if all_stats:
    print(f"\n\n{'='*60}")
    print("  SUMMARY COMPARISON")
    print(f"{'='*60}")
    df = pd.DataFrame(all_stats).set_index("profile")
    cols = ["CAGR", "annualized_vol", "Sharpe", "Sortino", "max_drawdown", "Calmar", "hit_ratio"]
    print(df[cols].to_string(float_format=lambda x: f"{x:.4f}"))
