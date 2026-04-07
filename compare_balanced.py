"""
Compare two candidate Balanced (穩健型) profile configurations.
A = My recommendation: stock<=30%, full universe, upper=0.3, utility
B = User's proposal:  stock<=40%, exclude industry, upper=0.2, utility
"""
import copy
import pandas as pd
from engine.config import load_config
from engine.data_loader import load_all_data
from main import run_full_pipeline_markowitz

base_cfg = load_config("config.yaml")
data = load_all_data(base_cfg)

candidates = {
    "方案A (stock30%/upper30%/full)": {
        "constraints.upper": 0.3,
        "constraints.stock_type_limit": 0.3,
        "constraints.asset_upper": {},
        "optimizer.objective": "utility",
    },
    "方案B (stock40%/upper20%/no_ind)": {
        "constraints.upper": 0.2,
        "constraints.stock_type_limit": 0.4,
        "constraints.asset_upper": {},
        "optimizer.objective": "utility",
        "universe.industry_list": [],  # exclude industry
    },
}

all_stats = []

for name, overrides in candidates.items():
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
    
    print(f"  Objective: {cfg['optimizer']['objective']}")
    print(f"  Upper: {cfg['constraints']['upper']}")
    print(f"  Stock Limit: {cfg['constraints']['stock_type_limit']}")
    print(f"  Market List: {cfg['universe']['market_list']}")
    print(f"  Industry List: {cfg['universe']['industry_list']}")
    print(f"  Bond List: {cfg['universe']['bond_list']}")
    
    try:
        results, weights_df, returns_df = run_full_pipeline_markowitz(cfg, data)
        
        stats = results["Q"]["stats"]
        stats["profile"] = name
        all_stats.append(stats)
        
        last_w = weights_df.iloc[-1]
        print(f"\n  Latest Weights:")
        for asset, w in last_w.items():
            if w > 0.001:
                print(f"    {asset}: {w:.1%}")
        
        # Also compute average stock vs bond allocation
        stock_cols = [c for c in weights_df.columns if c not in ["投資級債", "非投資級債", "新興市場債"]]
        bond_cols = [c for c in weights_df.columns if c in ["投資級債", "非投資級債", "新興市場債"]]
        avg_stock = weights_df[stock_cols].sum(axis=1).mean() if stock_cols else 0
        avg_bond = weights_df[bond_cols].sum(axis=1).mean() if bond_cols else 0
        print(f"\n  Average Stock Allocation: {avg_stock:.1%}")
        print(f"  Average Bond Allocation: {avg_bond:.1%}")
        
        print(f"\n  Performance (Q Rebalance):")
        print(f"    CAGR:      {stats['CAGR']:.2%}")
        print(f"    Vol:       {stats['annualized_vol']:.2%}")
        print(f"    Sharpe:    {stats['Sharpe']:.3f}")
        print(f"    Sortino:   {stats['Sortino']:.3f}")
        print(f"    Max DD:    {stats['max_drawdown']:.2%}")
        print(f"    Calmar:    {stats['Calmar']:.3f}")
        print(f"    Hit Ratio: {stats['hit_ratio']:.1%}")
        
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

if all_stats:
    print(f"\n\n{'='*60}")
    print("  COMPARISON TABLE")
    print(f"{'='*60}")
    df = pd.DataFrame(all_stats).set_index("profile")
    cols = ["CAGR", "annualized_vol", "Sharpe", "Sortino", "max_drawdown", "Calmar", "hit_ratio"]
    print(df[cols].to_string(float_format=lambda x: f"{x:.4f}"))
