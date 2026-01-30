from __future__ import annotations
import numpy as np
import pandas as pd

def period_returns(prices: pd.Series, method: str = "simple") -> pd.Series:
    if method == "simple":
        return prices.pct_change().dropna()
    if method == "log":
        return np.log(prices / prices.shift(1)).dropna()
    raise ValueError("method must be 'simple' or 'log'")
