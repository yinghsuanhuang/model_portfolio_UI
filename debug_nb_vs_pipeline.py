from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from pandas.tseries.offsets import MonthEnd

# ====== ensure project root in sys.path ======
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.config import load_config
from engine.data_loader import load_all_data
from main import run_full_pipeline_markowitz


def _print_header(title: str):
    print("\n" + "=" * 20 + f" {title} " + "=" * 20)


def _safe_read_csv(path: str) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, errors="coerce")
    return df


def _coerce_month_end_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df.index = df.index + MonthEnd(0)
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()
    return df


def _immediate_nav_check(results: dict, rule: str):
    nav = results[rule]["nav"]
    print(f"\n================ IMMEDIATE NAV CHECK ================")
    print(f"Rebalance rule : {rule}")
    print(f"NAV start      : {nav.iloc[0]}")
    print(f"NAV end        : {nav.iloc[-1]}")
    print(f"Total return   : {nav.iloc[-1] / nav.iloc[0] - 1}")
    print("====================================================")
    print("\nNAV tail (last 5 rows):")
    print(nav.tail(5))


def main():
    cfg_path = "config.yaml"
    cfg = load_config(cfg_path)
    data = load_all_data(cfg)

    # ========= 1) Run pipeline Markowitz (same as UI uses) =========
    _print_header("RUN PIPELINE (Markowitz)")
    results_pipe, weights_pipe, returns_pipe = run_full_pipeline_markowitz(cfg, data)

    # normalize index to month-end (safety)
    weights_pipe = _coerce_month_end_index(weights_pipe)
    returns_pipe = _coerce_month_end_index(returns_pipe)

    print("PIPE weights shape:", weights_pipe.shape)
    print("PIPE returns shape:", returns_pipe.shape)
    print("PIPE date range:", returns_pipe.index.min(), "->", returns_pipe.index.max())

    # immediate nav check for the rule you care most (default Q, but also show M)
    rule_focus = "Q"
    if rule_focus not in results_pipe:
        rule_focus = "M"

    _immediate_nav_check(results_pipe, rule_focus)

    # ========= 2) Load notebook outputs if exist =========
    _print_header("LOAD NOTEBOOK CSV (optional)")
    nb_weights_path = "outputs/weights_nb.csv"
    nb_returns_path = "outputs/returns_nb.csv"

    weights_nb = _safe_read_csv(nb_weights_path)
    returns_nb = _safe_read_csv(nb_returns_path)

    if weights_nb is None or returns_nb is None:
        print("⚠️ Notebook CSV not found.")
        print(f"Expected: {nb_weights_path} and {nb_returns_path}")
        print("Please export from notebook once:")
        print('  df_weight.to_csv("outputs/weights_nb.csv")')
        print('  df_BT_history_ret.to_csv("outputs/returns_nb.csv")')
        print("\nI will still print PIPELINE diagnostics (A~D).")
    else:
        weights_nb = _coerce_month_end_index(weights_nb)
        returns_nb = _coerce_month_end_index(returns_nb)

        print("NB weights shape:", weights_nb.shape)
        print("NB returns shape:", returns_nb.shape)
        print("NB date range:", returns_nb.index.min(), "->", returns_nb.index.max())

    # ========= 3) Diagnostics A~D =========
    _print_header("A) PIPE returns_df NaN diagnostics")
    print("returns_df shape:", returns_pipe.shape)
    print("returns_df date range:", returns_pipe.index.min(), "->", returns_pipe.index.max())
    print("returns_df NaN count:", int(returns_pipe.isna().sum().sum()))
    print("returns_df NaN by col:\n", returns_pipe.isna().sum().sort_values(ascending=False))

    if returns_nb is not None:
        _print_header("B) NB df_BT_history_ret NaN diagnostics")
        print("NB returns shape:", returns_nb.shape)
        print("NB date range:", returns_nb.index.min(), "->", returns_nb.index.max())
        print("NB NaN count:", int(returns_nb.isna().sum().sum()))
        print("NB NaN by col:\n", returns_nb.isna().sum().sort_values(ascending=False))

    _print_header("C) Sample month returns compare (PIPE vs NB)")
    # pick a few dates that should exist
    sample_dates = ["2012-01-31", "2012-02-29", "2012-03-31"]
    sample_dates = [pd.Timestamp(d) + MonthEnd(0) for d in sample_dates]

    print("PIPE sample dates found:", [d for d in sample_dates if d in returns_pipe.index])
    print("PIPE sample:\n", returns_pipe.loc[[d for d in sample_dates if d in returns_pipe.index]].head())

    if returns_nb is not None:
        print("\nNB sample dates found:", [d for d in sample_dates if d in returns_nb.index])
        print("NB sample:\n", returns_nb.loc[[d for d in sample_dates if d in returns_nb.index]].head())

    _print_header("D) Risk window NaN before fill (last lookback months)")
    lookback = int(cfg["risk"]["lookback_months"])
    win_pipe = returns_pipe.iloc[-lookback:].copy()
    print("PIPE window len:", len(win_pipe))
    print("PIPE window NaN before fill:", int(win_pipe.isna().sum().sum()))

    if returns_nb is not None:
        win_nb = returns_nb.iloc[-lookback:].copy()
        print("NB window len:", len(win_nb))
        print("NB window NaN before fill:", int(win_nb.isna().sum().sum()))

    # ========= 4) More: direct diff on overlapping period =========
    if returns_nb is not None:
        _print_header("EXTRA) PIPE vs NB: returns absolute diff (overlap)")
        common_idx = returns_pipe.index.intersection(returns_nb.index)
        common_cols = returns_pipe.columns.intersection(returns_nb.columns)

        print("Common idx len:", len(common_idx))
        print("Common cols:", list(common_cols))

        if len(common_idx) > 0 and len(common_cols) > 0:
            rp = returns_pipe.loc[common_idx, common_cols].copy()
            rn = returns_nb.loc[common_idx, common_cols].copy()

            # show where they differ most
            diff = (rp - rn).abs()
            # summary per asset
            asset_max = diff.max().sort_values(ascending=False)
            print("\nMax abs diff per asset:\n", asset_max)

            # top 10 (date, asset) differences
            stacked = diff.stack().sort_values(ascending=False)
            print("\nTop 15 (date, asset) abs diffs:")
            print(stacked.head(15))

        else:
            print("No overlap in index/columns; likely month-end alignment or naming mismatch.")

    _print_header("DONE")
    print("Now copy/paste the output back to me (especially sections A~D + EXTRA).")


if __name__ == "__main__":
    main()
