from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.tseries.offsets import MonthEnd


# ============================================================
# TAA 訊號引擎
# ------------------------------------------------------------
# 三層判斷（總體 > 市場 > 評價）：
#   1. 總體面：PMI / NFP / Fed 三項各 +1/0/-1 → 加總定方向
#   2. 市場面：SPX 月底 vs 200MA → 開關/否決，觸及則標記 meeting_flag
#   3. 評價面：ERP vs ±1σ → 決定 X 的乘數
# ΔX = direction × X × multiplier
# 缺資料的指標一律給 0 分（不誤判方向）
# ============================================================


def _fed_score_series(fdtr: pd.Series) -> pd.Series:
    """
    Fed 升降息循環：
      diff > 0（升息）→ -1
      diff < 0（降息）→ +1
      diff == 0：連 2 期不變 → 0；否則延續上一個非零方向
    """
    diff = fdtr.diff()
    scores: list[int] = []
    last_dir = 0
    prev_diff = np.nan

    for d in diff:
        if pd.isna(d):
            s = 0
        elif d > 0:
            last_dir = -1
            s = -1
        elif d < 0:
            last_dir = 1
            s = 1
        else:  # d == 0
            if (not pd.isna(prev_diff)) and prev_diff == 0:
                last_dir = 0
                s = 0
            else:
                s = last_dir
        scores.append(s)
        prev_diff = d

    return pd.Series(scores, index=fdtr.index, dtype=int)


def compute_factor_scores(
    taa_data: dict,
    config: dict,
    nfp_threshold: float | None = None,
    pmi_threshold: float | None = None,
) -> pd.DataFrame:
    """
    回傳月頻訊號表（X-independent），欄位：
      pmi_score / nfp_score / fed_score / macro_score / direction
      market_above_10MA / erp_score
    index = 三張表月頻索引的聯集
    """
    taa_cfg = config.get("taa", {})
    if nfp_threshold is None:
        nfp_threshold = float(taa_cfg.get("nfp_threshold", 50))
    if pmi_threshold is None:
        pmi_threshold = float(taa_cfg.get("pmi_threshold", 50))

    macro = taa_data["macro"]
    market = taa_data["market"]
    val = taa_data["valuation"]

    # ── 總體面 ──
    pmi = macro["pmi"]
    pmi_3, pmi_6 = pmi.rolling(3).mean(), pmi.rolling(6).mean()
    pmi_score = pd.Series(0, index=macro.index, dtype=int)
    pmi_score[(pmi > pmi_threshold) & (pmi_3 > pmi_6)] = 1
    pmi_score[(pmi < pmi_threshold) & (pmi_3 < pmi_6)] = -1

    nfp = macro["nfp"]
    nfp_3, nfp_6 = nfp.rolling(3).mean(), nfp.rolling(6).mean()
    nfp_score = pd.Series(0, index=macro.index, dtype=int)
    nfp_score[(nfp > nfp_threshold) & (nfp_3 > nfp_6)] = 1
    nfp_score[(nfp < nfp_threshold) & (nfp_3 < nfp_6)] = -1

    fed_score = _fed_score_series(macro["fdtr"])

    # ── 市場面 ──
    market_above = (market["spx"] > market["ma200"])

    # ── 評價面 ──
    erp_score = pd.Series(0, index=val.index, dtype=int)
    erp_score[val["erp"] > val["sigma_plus1"]] = 1
    erp_score[val["erp"] < val["sigma_minus1"]] = -1

    # ── 組裝到聯集索引 ──
    idx = macro.index.union(market.index).union(val.index).sort_values()

    df = pd.DataFrame(index=idx)
    df["pmi_score"] = pmi_score.reindex(idx).fillna(0).astype(int)
    df["nfp_score"] = nfp_score.reindex(idx).fillna(0).astype(int)
    df["fed_score"] = fed_score.reindex(idx).fillna(0).astype(int)
    df["macro_score"] = df["pmi_score"] + df["nfp_score"] + df["fed_score"]
    df["direction"] = np.sign(df["macro_score"]).astype(int)
    df["market_above_10MA"] = market_above.reindex(idx).fillna(False).astype(bool)
    df["erp_score"] = erp_score.reindex(idx).fillna(0).astype(int)

    return df


def _multiplier(direction: int, erp_score: int, mult_cfg: dict) -> float:
    """評價面乘數查表（§5.2）。"""
    if direction == 0:
        return 0.0
    plus_1 = float(mult_cfg.get("plus_1", 1.00))
    zero = float(mult_cfg.get("zero", 0.75))
    minus_1 = float(mult_cfg.get("minus_1", 0.50))
    if direction > 0:  # 加碼
        return {1: plus_1, 0: zero, -1: minus_1}[erp_score]
    else:              # 減碼
        return {1: minus_1, 0: zero, -1: plus_1}[erp_score]


def _bucket_cols(config: dict, columns: pd.Index) -> tuple[list[str], list[str]]:
    """從 config.universe 推導股票桶 / 債券桶欄名（與權重表欄名比對）。"""
    market_list = config["universe"].get("market_list") or []
    industry_list = config["universe"].get("industry_list") or []
    bond_list = config["universe"].get("bond_list") or []

    stock_names = [m.replace(" ", "_") for m in market_list] + list(industry_list)
    stock_cols = [c for c in stock_names if c in columns]
    bond_cols = [c for c in bond_list if c in columns]
    return stock_cols, bond_cols


def apply_taa_weights(
    w_saa: pd.Series,
    delta: float,
    stock_cols: list[str],
    bond_cols: list[str],
    add_target: str,
    reduce_target: str,
) -> pd.Series:
    """
    將 ΔX 套到 SAA 權重（豁免 SAA 約束，僅維持 [0,1] 與 Σw=1）：
      加碼 (delta>0)：債券等比例↓ delta，全進 add_target(SPX)
      減碼 (delta<0)：股票等比例↓|delta|，全進 reduce_target(投資級債)
    """
    w = w_saa.copy().astype(float)

    if delta > 0:
        bsum = float(w[bond_cols].sum()) if bond_cols else 0.0
        if bsum <= 0:
            return w  # 無債券部位可移出 → 無法加碼
        r = min(delta, bsum)
        for c in bond_cols:
            w[c] = w[c] * (1 - r / bsum)
        if add_target in w.index:
            w[add_target] = w[add_target] + r

    elif delta < 0:
        ssum = float(w[stock_cols].sum()) if stock_cols else 0.0
        if ssum <= 0:
            return w  # 無股票部位可移出 → 無法減碼
        r = min(-delta, ssum)
        for c in stock_cols:
            w[c] = w[c] * (1 - r / ssum)
        if reduce_target in w.index:
            w[reduce_target] = w[reduce_target] + r

    return w


def compute_reference_signal(
    taa_data: dict,
    config: dict,
    nfp_threshold: float | None = None,
    pmi_threshold: float | None = None,
) -> dict:
    """
    試算「參考期」（= 回測最後一個月，與訊號卡一致）的訊號，與 X 無關。
    供 UI 在按 Run 前決定滑桿上限（本期模型建議 ΔX = profile_X × multiplier）。
    """
    scores = compute_factor_scores(taa_data, config, nfp_threshold, pmi_threshold)
    bt_end = pd.to_datetime(config["dates"]["backtest_end"]) + MonthEnd(0)
    obs = bt_end - MonthEnd(1)            # 1 個月落後（與回測決策一致）
    sub = scores.loc[:obs]
    mult_cfg = config.get("taa", {}).get("valuation_multipliers", {})

    if sub.empty:
        return {"date": bt_end, "obs_date": None, "direction": 0,
                "erp_score": 0, "multiplier": 0.0, "market_above_10MA": False}

    s = sub.iloc[-1]
    direction = int(s["direction"])
    erp = int(s["erp_score"])
    above = bool(s["market_above_10MA"])
    meeting_flag = (direction > 0 and not above) or (direction < 0 and above)
    return {
        "date": bt_end,
        "obs_date": sub.index[-1],
        "direction": direction,
        "erp_score": erp,
        "multiplier": _multiplier(direction, erp, mult_cfg),
        "market_above_10MA": above,
        "meeting_flag": meeting_flag,
    }


def build_taa_weights(
    saa_weights_df: pd.DataFrame,
    taa_data: dict,
    config: dict,
    X: float,
    nfp_threshold: float | None = None,
    pmi_threshold: float | None = None,
    last_period_override: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    依 SAA 月頻權重，計算每月 TAA 訊號並套用，回傳：
      - taa_weights_df：TAA 調整後權重（欄/列同 saa_weights_df）
      - signals_df：對齊到 saa_weights_df.index 的訊號明細（含 delta_x、meeting_flag）

    時間對齊：持有月 D 的權重使用「D 的前一月末」可觀測之訊號（與 SAA t-1 決策一致，避免偷看）。
    """
    taa_cfg = config.get("taa", {})
    mult_cfg = taa_cfg.get("valuation_multipliers", {})
    add_target = taa_cfg.get("add_target", "SPX_Index")
    reduce_target = taa_cfg.get("reduce_target", "投資級債")

    scores = compute_factor_scores(taa_data, config, nfp_threshold, pmi_threshold)

    stock_cols, bond_cols = _bucket_cols(config, saa_weights_df.columns)

    # ── 1 個月落後對齊（as-of ffill）──
    obs_index = saa_weights_df.index - MonthEnd(1)
    prim_cols = ["pmi_score", "nfp_score", "fed_score", "macro_score",
                 "direction", "market_above_10MA", "erp_score"]
    aligned = (
        scores[prim_cols]
        .reindex(scores.index.union(obs_index))
        .sort_index()
        .ffill()
        .reindex(obs_index)
    )
    aligned.index = saa_weights_df.index

    # 缺值補 0/False（早期無資料月份）
    for c in prim_cols:
        if c == "market_above_10MA":
            aligned[c] = aligned[c].fillna(False).astype(bool)
        else:
            aligned[c] = aligned[c].fillna(0).astype(int)

    # ── 衍生欄位 + 套權重 ──
    taa_rows = []
    sig_rows = []
    last_date = saa_weights_df.index[-1]
    for D in saa_weights_df.index:
        s = aligned.loc[D]
        direction = int(s["direction"])
        erp_score = int(s["erp_score"])
        above = bool(s["market_above_10MA"])

        meeting_flag = (
            (direction > 0 and not above) or (direction < 0 and above)
        )

        if D == last_date and last_period_override is not None:
            direction = last_period_override["direction"]
            delta = last_period_override["delta_x"]
            mult = _multiplier(direction, erp_score, mult_cfg)
            meeting_flag = False  # 使用者已手動決策
        else:
            mult = _multiplier(direction, erp_score, mult_cfg)
            delta = direction * float(X) * mult

        w_taa = apply_taa_weights(
            saa_weights_df.loc[D], delta,
            stock_cols, bond_cols, add_target, reduce_target,
        )
        taa_rows.append(w_taa.values)

        sig_rows.append({
            "pmi_score": int(s["pmi_score"]),
            "nfp_score": int(s["nfp_score"]),
            "fed_score": int(s["fed_score"]),
            "macro_score": int(s["macro_score"]),
            "direction": direction,
            "market_above_10MA": above,
            "erp_score": erp_score,
            "multiplier": mult,
            "delta_x": delta,
            "meeting_flag": bool(meeting_flag),
        })

    taa_weights_df = pd.DataFrame(
        taa_rows, index=saa_weights_df.index, columns=saa_weights_df.columns
    )
    signals_df = pd.DataFrame(sig_rows, index=saa_weights_df.index)

    return taa_weights_df, signals_df
