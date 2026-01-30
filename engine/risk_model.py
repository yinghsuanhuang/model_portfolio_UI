# engine/risk_model.py
from __future__ import annotations
import pandas as pd
from sklearn.covariance import LedoitWolf

def build_covariance(
    history_returns: pd.DataFrame,
    lookback_months: int,
    cov_method: str,
    annualize_factor: float,
) -> pd.DataFrame:
    window = history_returns.iloc[-lookback_months:].copy()
    window = window.ffill().bfill()

    if cov_method.lower() == "ledoitwolf":
        lw = LedoitWolf().fit(window.values)
        cov = pd.DataFrame(
            lw.covariance_,
            index=window.columns,
            columns=window.columns,
        )
    elif cov_method.lower() == "sample":
        cov = window.cov()
    else:
        raise ValueError("cov_method must be 'ledoitwolf' or 'sample'")

    return cov * float(annualize_factor)
