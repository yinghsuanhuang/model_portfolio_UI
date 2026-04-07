"""
Analyze benchmark options for the Conservative profile.
Current benchmark: 60% LUCRTRUU + 20% LEGATRUU + 20% LG30TRUU (all bonds)
Test alternatives: 100% LEGATRUU, Equal weight, etc.
"""
import pandas as pd
import numpy as np
from engine.config import load_config
from engine.data_loader import load_all_data
from engine.backtest import run_all_frequencies_monthly

cfg = load_config("config.yaml")
data = load_all_data(cfg)

bm_raw = data["benchmark"]
print("Benchmark columns:", bm_raw.columns.tolist())
print(f"Date range: {bm_raw.index[0].date()} to {bm_raw.index[-1].date()}")
print(f"\nFirst 5 rows (price levels):")
print(bm_raw.head())

bm_ret = bm_raw.pct_change().dropna()

# Also get Conservative asset returns for comparison
bond_ind = data["bond_industry"]
conservative_ret = bond_ind[["投資級債", "非投資級債"]].dropna()

# Align date range
bt_start = pd.to_datetime(cfg["dates"]["backtest_start"])
bt_end = pd.to_datetime(cfg["dates"]["backtest_end"])
bm_ret = bm_ret.loc[bt_start:bt_end]
conservative_ret = conservative_ret.loc[bt_start:bt_end]

# Test different benchmark configs
benchmarks = {
    "現行 60/20/20": [0.6, 0.2, 0.2],
    "100% LUCRTRUU (US Credit)": [1.0, 0.0, 0.0],
    "100% LEGATRUU (Global Agg)": [0.0, 1.0, 0.0],
    "100% LG30TRUU (Long Gov)": [0.0, 0.0, 1.0],
    "Equal 1/3": [1/3, 1/3, 1/3],
}

# Also test a "pure IG/Non-IG" benchmark
# 80% IG + 20% Non-IG (matching Conservative default weights)
print("\n\n" + "="*60)
print(" BENCHMARK COMPARISON")
print("="*60)

all_stats = []
for name, weights in benchmarks.items():
    w_df = pd.DataFrame(
        [weights] * len(bm_ret),
        index=bm_ret.index,
        columns=bm_ret.columns,
    )
    results = run_all_frequencies_monthly(
        bm_ret, w_df,
        starting_capital=1.0, trading_cost_bps=0.0, rf_annual=0.0,
    )
    s = results["Q"]["stats"]
    s["name"] = name
    all_stats.append(s)
    print(f"\n[{name}]")
    print(f"  CAGR={s['CAGR']:.2%}  Vol={s['annualized_vol']:.2%}  Sharpe={s['Sharpe']:.3f}  MDD={s['max_drawdown']:.2%}")

# Also test Conservative assets as benchmark (80% IG + 20% Non-IG)
print(f"\n--- Conservative Assets as Benchmark ---")
cons_weights = [[0.8, 0.2]] * len(conservative_ret)
w_cons = pd.DataFrame(cons_weights, index=conservative_ret.index, columns=["投資級債", "非投資級債"])
results_cons = run_all_frequencies_monthly(
    conservative_ret, w_cons,
    starting_capital=1.0, trading_cost_bps=0.0, rf_annual=0.0,
)
s = results_cons["Q"]["stats"]
s["name"] = "80% IG + 20% Non-IG (Conservative Match)"
all_stats.append(s)
print(f"  CAGR={s['CAGR']:.2%}  Vol={s['annualized_vol']:.2%}  Sharpe={s['Sharpe']:.3f}  MDD={s['max_drawdown']:.2%}")

print(f"\n\n{'='*60}")
print("  SUMMARY")
print(f"{'='*60}")
df = pd.DataFrame(all_stats).set_index("name")
cols = ["CAGR", "annualized_vol", "Sharpe", "Sortino", "max_drawdown", "Calmar"]
print(df[cols].to_string(float_format=lambda x: f"{x:.4f}"))
