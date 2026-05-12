"""
Compare 5 profiles: Conservative, Balanced, Growth, Aggressive(70%), Aggressive(80%)
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
    "保守型": {
        "constraints.upper": 1.0,
        "constraints.stock_type_limit": 0.0,
        "constraints.asset_upper": {"非投資級債": 0.2},
        "optimizer.objective": "min_variance",
        "universe.market_list": [],
        "universe.industry_list": [],
        "universe.bond_list": ["投資級債", "非投資級債"],
    },
    "穩健型(方案B)": {
        "constraints.upper": 0.2,
        "constraints.stock_type_limit": 0.4,
        "constraints.asset_upper": {},
        "optimizer.objective": "utility",
        "universe.industry_list": [],
    },
    "成長型": {
        "constraints.upper": 0.2,
        "constraints.stock_type_limit": 0.55,
        "constraints.asset_upper": {},
        "optimizer.objective": "sharpe",
    },
    "積極型(stock70%)": {
        "constraints.upper": 0.5,
        "constraints.stock_type_limit": 0.7,
        "constraints.asset_upper": {},
        "optimizer.objective": "sortino",
    },
    "積極型(stock80%)": {
        "constraints.upper": 0.5,
        "constraints.stock_type_limit": 0.8,
        "constraints.asset_upper": {},
        "optimizer.objective": "sortino",
    },
}

all_stats = []

for name, overrides in profiles.items():
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    cfg = copy.deepcopy(base_cfg)
    for key, val in overrides.items():
        parts = key.split(".")
        d = cfg
        for p in parts[:-1]:
            d = d[p]
        d[parts[-1]] = val
    
    try:
        results, weights_df, returns_df = run_full_pipeline_markowitz(cfg, data)
        stats = results["Q"]["stats"]
        stats["profile"] = name
        all_stats.append(stats)
        
        last_w = weights_df.iloc[-1]
        print(f"  Latest Weights:")
        for asset, w in last_w.items():
            if w > 0.001:
                print(f"    {asset}: {w:.1%}")
        
        print(f"  CAGR={stats['CAGR']:.2%}  Vol={stats['annualized_vol']:.2%}  Sharpe={stats['Sharpe']:.3f}  MDD={stats['max_drawdown']:.2%}")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

if all_stats:
    print(f"\n\n{'='*60}")
    print("  FULL COMPARISON TABLE")
    print(f"{'='*60}")
    df = pd.DataFrame(all_stats).set_index("profile")
    cols = ["CAGR", "annualized_vol", "Sharpe", "Sortino", "max_drawdown", "Calmar", "hit_ratio"]
    print(df[cols].to_string(float_format=lambda x: f"{x:.4f}"))
