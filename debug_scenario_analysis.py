
import pandas as pd
import numpy as np
from engine.data_loader import load_all_data
from engine.optimizer import solve_weights
from engine.config import load_config

def run_scenario_analysis():
    # 1. Load Config
    cfg = load_config("config.yaml")
    
    # 2. Setup Data (Simulation)
    # Using the same logic as before to get the last available window
    data_map = load_all_data(cfg)
    dfs = []
    if "market" in data_map: dfs.append(data_map["market"])
    if "bond_industry" in data_map: dfs.append(data_map["bond_industry"])
    full_df = pd.concat(dfs, axis=1).dropna()
    
    market_list = cfg["universe"]["market_list"]
    industry_list = cfg["universe"]["industry_list"]
    bond_list = cfg["universe"]["bond_list"]
    asset_names = [m.replace(" ", "_") for m in market_list] + industry_list + bond_list
    valid_assets = [c for c in asset_names if c in full_df.columns]
    
    # Conservative Universe: only Bond list (subset)
    # The app actually filters universe by setting market/industry lists to empty
    # But for this debug script, we need to manually ensure we are optimizing over the relevant assets
    # In 'solve_weights', it uses 'mu.index'. So we should filter 'mu' to only contain bonds.
    
    # Actually, the app logic in 'run_full_pipeline_markowitz' calls 'build_expected_return'
    # which respects the config's universe lists.
    # Let's verify what the app does for Conservative:
    # base_cfg["universe"]["market_list"] = []
    # base_cfg["universe"]["industry_list"] = []
    # base_cfg["universe"]["bond_list"] = ["投資級債", "非投資級債"]
    # So effectively, only these two assets exist in the universe? 
    # Wait, the user mentioned emerging market bond (新興市場債) in the previous debug output.
    # Let's check app.py again.
    
    # app.py L147: base_cfg["universe"]["bond_list"] = ["投資級債", "非投資級債"]
    # Wait, if EM Bond is NOT in the list, then it won't be in the weights at all!
    # But the user's previous weights.csv showed EM Bond.
    # Ah, the user might have customized it or I might be misremembering the app.py change.
    
    # Let's assume the standard Conservative profile as defined in app.py:
    # It REMOVES '新興市場債' from bond_list!
    # "st.sidebar.info("保守型預設：\n- 僅包含 投資級債 & 非投資級債...)"
    
    # IF the universe only has 2 assets: IG Bond and Non-IG Bond.
    # And Stock Limit = 0 (irrelevant if stocks not in universe).
    # And Non-IG Limit = 20%.
    # Then IG Bond MUST be at least 80%.
    # If Non-IG Limit = 60%, then IG Bond must be at least 40%.
    
    # Let's strictly follow the 'Conservative' config I see in app.py
    conservative_assets = ["投資級債", "非投資級債"] 
    
    # Filter data
    # The user is likely seeing the result of the *latest* rebalancing.
    # The app uses a Lookback window (e.g., 36 months) to calculate Sigma.
    # Let's verify the last 36 months of volatility.
    
    lookback = 36
    # Data is already returns, do NOT pct_change
    returns_df = full_df[conservative_assets].dropna()
    
    # Use the last 'lookback' months
    window = returns_df.iloc[-lookback:]
    
    # Calculate Mu / Sigma based on this window (as the optimizer does)
    # Note: App uses risk_model.build_covariance which might use LedoitWolf or Sample.
    # Default is likely LedoitWolf but let's just use Sample for quick debug or check config.
    # checking config... usually 'cov_method': 'ledoitwolf' or 'sample'.
    # We'll use sample covariance for transparency in this debug.
    
    mu_window = window.mean() * 12
    sigma_window = window.cov() * 12
    
    print(f"Data Window: Last {lookback} months ({window.index[0].date()} to {window.index[-1].date()})")
    print(f"Assets: {conservative_assets}")
    
    vol = np.sqrt(np.diag(sigma_window))
    print(f"\nAnnualized Volatility (Risk):")
    for i, name in enumerate(conservative_assets):
        print(f"  {name}: {vol[i]:.2%}")
        
    corr = window.corr()
    print(f"\nCorrelation Matrix:\n{corr}")
    
    print(f"\nMu (Annualized):\n{mu_window}")
    
    # Define Scenarios
    limits = [0.2, 0.6]
    objectives = ["sortino", "sharpe", "utility", "min_variance"]
    
    for limit in limits:
        print(f"\n{'='*20} Scenario: Non-IG Limit = {limit:.0%} {'='*20}")
        
        # Configure Config
        cfg["constraints"]["lower"] = 0.0
        cfg["constraints"]["upper"] = 1.0
        cfg["constraints"]["stock_type_limit"] = 0.0
        cfg["constraints"]["asset_upper"] = {"非投資級債": limit}
        cfg["universe"]["market_list"] = []
        cfg["universe"]["industry_list"] = []
        
        for obj in objectives:
            cfg["optimizer"]["objective"] = obj
            
            # Reset params to defaults if needed
            cfg["optimizer"]["risk_aversion"] = 2.0
            cfg["risk"]["mar"] = 0.0
            
            try:
                w = solve_weights(mu_window, sigma_window, window, cfg)
                w_clean = w[w > 0.001]
                print(f"\n[Objective: {obj}]")
                print(w_clean.to_string())
            except Exception as e:
                print(f"\n[Objective: {obj}] Failed: {e}")

if __name__ == "__main__":
    run_scenario_analysis()
