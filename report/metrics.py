from __future__ import annotations
import pandas as pd

def summarize_stats(stats_by_rule: dict) -> pd.DataFrame:
    rows = []
    for rule, pack in stats_by_rule.items():
        s = pack["stats"]
        rows.append({
            "rebalance_rule": rule,
            "CAGR": s.get("CAGR"),
            "annualized_vol": s.get("annualized_vol"),
            "Sharpe": s.get("Sharpe"),
            "Sortino": s.get("Sortino"),
            "max_drawdown": s.get("max_drawdown"),
            "Calmar": s.get("Calmar"),
            "hit_ratio": s.get("hit_ratio"),
        })
    return pd.DataFrame(rows).set_index("rebalance_rule")
