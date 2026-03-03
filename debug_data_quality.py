
import pandas as pd
import numpy as np
from engine.data_loader import load_all_data
from engine.config import load_config

def check_data_quality():
    print("=== Checking Data Quality ===")
    cfg = load_config("config.yaml")
    data_map = load_all_data(cfg)
    
    # Extract relevant assets
    # We know from config that bond_list has "投資級債", "非投資級債"
    # These are likely in data_map['bond_industry'] or 'market' depending on how they are loaded
    # Let's check where they are.
    
    dfs = []
    if "market" in data_map: dfs.append(data_map["market"])
    if "bond_industry" in data_map: dfs.append(data_map["bond_industry"])
    full_df = pd.concat(dfs, axis=1)
    
    targets = ["投資級債", "非投資級債"]
    
    for asset in targets:
        if asset not in full_df.columns:
            print(f"❌ Asset '{asset}' not found in data!")
            continue
            
        series = full_df[asset].dropna()
        print(f"\n--- {asset} ---")
        print(f"Total Data Points: {len(series)}")
        print(f"Date Range: {series.index[0].date()} to {series.index[-1].date()}")
        
        # Check last 36 months specifically
        subset = series.iloc[-36:]
        print(f"Last 36 months count: {len(subset)}")
        
        # Check for Zeros
        zeros = (subset == 0).sum()
        if zeros > 0:
            print(f"⚠️  WARNING: Found {zeros} Zeros in last 36 months!")
            print(subset[subset == 0])
            
        # Check for NaNs (already dropped above, but check original full_df slicing)
        raw_subset = full_df[asset].tail(36)
        nans = raw_subset.isna().sum()
        if nans > 0:
             print(f"⚠️  WARNING: Found {nans} NaNs in last 36 months!")
        
        # Check Returns (Outliers)
        returns = subset.pct_change().dropna()
        print(f"Returns Stats (Last 36m):")
        print(returns.describe())
        
        # Identify extreme moves (> 10% in a month)
        outliers = returns[returns.abs() > 0.10]
        if not outliers.empty:
            print(f"⚠️  Extreme Returns (>10%):")
            print(outliers)
            
        # Show raw prices around outliers
        if not outliers.empty:
            print("Raw Prices around outliers:")
            for date in outliers.index:
                loc = subset.index.get_loc(date)
                start = max(0, loc-2)
                end = min(len(subset), loc+3)
                print(subset.iloc[start:end])
                
if __name__ == "__main__":
    check_data_quality()
