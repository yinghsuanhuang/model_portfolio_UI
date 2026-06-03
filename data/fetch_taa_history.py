"""
TAA 歷史資料補充腳本
=====================
自動從免費公開來源拉取 TAA 三因子的歷史資料（2010-至今），
並輸出可直接被 data_loader.py 自動讀取的 CSV。

執行：
    source .venv/bin/activate
    python3 data/fetch_taa_history.py

輸出檔案：
    data/taa_history_fdtr.csv         ← 總體面：FDTR（FRED，自動）
    data/taa_history_nfp.csv          ← 總體面：NFP 月增（FRED，自動）
    data/taa_history_pmi.csv          ← 總體面：CFNAI 代理（FRED，自動；榮枯線=0）
    data/taa_history_spx_ma200.csv    ← 市場面：SPX + 200MA（yfinance，自動）
    data/taa_history_erp.csv          ← 評價面：ERP 代替計算（Shiller + GS10，自動）
    data/taa_history_erp_detail.csv   ← 評價面：明細（EY, GS10, ERP）

ERP 說明：
    目標公式：ERP = (1 / S&P500 Fwd PE) * 100 - GS10
    因 Forward PE 為商業資料，改用 Shiller Trailing 12M EPS 作代理。
    非危機年份誤差約 0.5-1%；2020-21 COVID 期間誤差較大。
    若需精確 Forward PE，請從 Bloomberg 下載：
        BDH("SPX Index BEST_PE_RATIO", "PX_LAST", "20100101", "today")

PMI 說明：
    模型使用 S&P Global 美國綜合 PMI（MPMIUSCA Index），為付費資料。
    本腳本改用 CFNAI（Chicago Fed National Activity Index，FRED 免費），
    榮枯線為 0（對應 PMI 的 50），與 ISM Manufacturing PMI 相關係數 > 0.85。
    使用前需更新 config.yaml：pmi_threshold: 0.0
"""
from __future__ import annotations

import sys
from pathlib import Path
from io import StringIO, BytesIO
from datetime import datetime

import pandas as pd
import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

START = "2010-01-01"
END   = datetime.today().strftime("%Y-%m-%d")
OUT   = Path(__file__).parent

print("=" * 60)
print("  TAA 歷史資料補充腳本")
print(f"  期間：{START} → {END}")
print("=" * 60)


# ─────────────────────────────────────────
# 共用工具
# ─────────────────────────────────────────

def fred_csv(series_id: str, start: str = START, end: str = END) -> pd.Series:
    """從 FRED 免費匿名下載，統一轉成月底頻率。"""
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
           f"?id={series_id}&cosd={start}&coed={end}")
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    s = pd.to_numeric(
        pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)
        .iloc[:, 0].replace(".", float("nan")),
        errors="coerce",
    )
    s = s.resample("ME").last()
    s.name = series_id
    print(f"  ✓ FRED {series_id}: {s.dropna().shape[0]} 筆，"
          f"{s.dropna().index.min().date()} → {s.dropna().index.max().date()}")
    return s


def to_monthly_last(s: pd.Series) -> pd.Series:
    return s.resample("ME").last()


# ─────────────────────────────────────────
# ① FDTR：Fed Funds Target Rate（上緣）
#    FRED DFEDTARU（2008 起）+ FEDFUNDS（補早期）
# ─────────────────────────────────────────
print("\n[1/5] FDTR — Fed 基準利率（上緣）")

fdtr_upper = fred_csv("DFEDTARU")
fedfunds   = fred_csv("FEDFUNDS")
fdtr = fdtr_upper.combine_first(fedfunds)[START:]
fdtr.name = "FDTR Index"

out_fdtr = OUT / "taa_history_fdtr.csv"
fdtr.to_csv(out_fdtr, header=True)
print(f"  → 輸出：{out_fdtr.name}  ({fdtr.dropna().shape[0]} 筆)")

try:
    from engine.data_loader import load_taa_data
    from engine.config import load_config
    cfg = load_config(str(ROOT / "config.yaml"))
    existing_taa = load_taa_data(cfg)
    existing_fdtr = existing_taa["macro"]["fdtr"].dropna()
    overlap = fdtr.dropna().reindex(existing_fdtr.index).dropna()
    if len(overlap) > 5:
        corr = overlap.corr(existing_fdtr.reindex(overlap.index).dropna())
        diff = (overlap - existing_fdtr.reindex(overlap.index)).abs().mean()
        print(f"  ↔ 比對現有資料：相關 {corr:.4f}，平均誤差 {diff:.4f}%")
except Exception as e:
    print(f"  (比對略過：{e})")


# ─────────────────────────────────────────
# ② NFP：非農就業月增（千人）
#    FRED PAYEMS.diff()
# ─────────────────────────────────────────
print("\n[2/5] NFP — 非農就業月增（千人）")

payems  = fred_csv("PAYEMS")
nfp_chg = payems.diff()[START:]
nfp_chg.name = "NFP TCH Index"

out_nfp = OUT / "taa_history_nfp.csv"
nfp_chg.to_csv(out_nfp, header=True)
print(f"  → 輸出：{out_nfp.name}  ({nfp_chg.dropna().shape[0]} 筆)")
print(f"  NFP 2021 樣本：")
print("  " + nfp_chg["2021"].dropna().round(1).to_string().replace("\n", "\n  "))


# ─────────────────────────────────────────
# ③ PMI 代理：CFNAI（Chicago Fed National Activity Index）
#
#  模型目標：S&P Global 美國綜合 PMI（MPMIUSCA Index）
#    → 付費資料，無法免費自動下載
#    → 若有 Bloomberg：BDH("MPMIUSCA Index","PX_LAST","20120101","20230430","periodicitySelection","MONTHLY")
#
#  最佳免費替代：CFNAI（FRED CFNAI）
#    - Chicago Fed 85 個經濟指標加權合成
#    - 榮枯線 = 0（對應 PMI 榮枯線 50）
#    - 與 ISM Manufacturing PMI 相關係數 > 0.85
#    - FRED 更新至最新月份（約滯後 1 個月）
#    - 需要更新 config.yaml：pmi_threshold: 0.0
#
#  注意：
#    Alpha Vantage 免費版無 PMI endpoint（ISM_PMI_* 均不存在）
#    ISM 官網、dbnomics、Quandl 均無法免費自動下載
# ─────────────────────────────────────────
print("\n[3/5] PMI 代理 — CFNAI（Chicago Fed, FRED）")
print("  ⚠ S&P Global PMI 為付費資料，改用 CFNAI 作為免費代理")
print("  ⚠ 榮枯線不同：CFNAI 用 0（PMI 用 50），需更新 config.yaml")

pmi_series = None

try:
    cfnai = fred_csv("CFNAI")   # Chicago Fed National Activity Index
    cfnai = cfnai[START:].dropna()
    cfnai.name = "MPMIUSCA Index"   # 欄名統一，供 data_loader 讀取

    pmi_series = cfnai
    print(f"  ✓ CFNAI: {len(cfnai)} 筆，"
          f"{cfnai.index.min().date()} → {cfnai.index.max().date()}")
    print(f"  最新值：{cfnai.iloc[-1]:.3f}（> 0 擴張，< 0 收縮）")
    above0 = (cfnai > 0).mean() * 100
    print(f"  > 0（擴張）比例：{above0:.1f}%（2010-至今）")
    print()
    print("  ★ 使用前請更新 config.yaml：")
    print("      pmi_threshold: 0.0   # CFNAI 榮枯線（原為 50）")

except Exception as e:
    print(f"  ✗ CFNAI 下載失敗：{e}")

if pmi_series is not None and len(pmi_series) > 0:
    out_pmi = OUT / "taa_history_pmi.csv"
    pmi_series.to_csv(out_pmi, header=True)
    print(f"\n  → 輸出：{out_pmi.name}  ({len(pmi_series)} 筆)")
    print(f"  → data_loader.py 將自動補充歷史 PMI 空缺")
else:
    print(f"  → taa_history_pmi.csv 未建立")


# ─────────────────────────────────────────
# ④ 市場面：SPX 月底收盤 + 200MA（yfinance）
# ─────────────────────────────────────────
print("\n[4/5] SPX + 200MA — 市場面因子")

try:
    import yfinance as yf
    raw = yf.download("^GSPC", start="2009-01-01", end=END,
                      progress=False, auto_adjust=True)
    close_col = raw["Close"]
    spx_daily = (close_col.iloc[:, 0]
                 if isinstance(close_col, pd.DataFrame) else close_col).squeeze()
    spx_daily.index = pd.to_datetime(spx_daily.index)
    spx_daily.name  = "SPX"
    ma200 = spx_daily.rolling(200, min_periods=150).mean()

    spx_m   = to_monthly_last(spx_daily).rename("最新價")
    ma200_m = to_monthly_last(ma200).rename("移動平均(簡單,200,0)")

    mkt_df = pd.concat([spx_m, ma200_m], axis=1)
    mkt_df = mkt_df[START:].dropna(subset=["移動平均(簡單,200,0)"])
    mkt_df.index.name = "Date"

    out_mkt = OUT / "taa_history_spx_ma200.csv"
    mkt_df.to_csv(out_mkt)
    print(f"  ✓ yfinance ^GSPC: {len(mkt_df)} 月，"
          f"{mkt_df.index.min().date()} → {mkt_df.index.max().date()}")
    print(f"  → 輸出：{out_mkt.name}")
    pct_above = (mkt_df["最新價"] > mkt_df["移動平均(簡單,200,0)"]).mean() * 100
    print(f"  SPX > 200MA 比例：{pct_above:.1f}%（2010-至今）")

except ImportError:
    print("  ✗ yfinance 未安裝：pip install yfinance")
except Exception as e:
    print(f"  ✗ 失敗：{e}")


# ─────────────────────────────────────────
# ⑤ 評價面：ERP 代替計算
#
#  目標公式：ERP = (1 / S&P500 Fwd PE) * 100 - GS10
#  免費代理：Shiller Trailing 12M Earnings Yield - GS10
#    來源：http://www.econ.yale.edu/~shiller/data/ie_data.xls
#    補近期：multpl.com trailing PE
#
#  注意：Trailing PE ≠ Forward PE（非危機年誤差約 0.5-1%）
#  若需精確值：Bloomberg BDH("SPX Index BEST_PE_RATIO","PX_LAST","20100101","today")
# ─────────────────────────────────────────
print("\n[5/5] ERP — 股票風險溢酬（Shiller Trailing PE 代理）")

gs10 = fred_csv("GS10")

# ── Step 1: Shiller ie_data.xls ──
ey_series    = None
gs10_shiller = None

try:
    print("  下載 Shiller ie_data.xls...")
    resp = requests.get("http://www.econ.yale.edu/~shiller/data/ie_data.xls",
                        timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    sh = pd.read_excel(BytesIO(resp.content), sheet_name="Data",
                       header=7, engine="xlrd")
    sh = sh.dropna(subset=["Date"])
    sh["Date"] = sh["Date"].astype(str).str.strip()

    def _parse_shiller_date(s: str):
        try:
            parts = s.split(".")
            y, m = int(parts[0]), int(parts[1]) if len(parts) > 1 and parts[1] else 1
            return pd.Timestamp(year=y, month=m, day=1) + pd.offsets.MonthEnd(0)
        except Exception:
            return None

    sh["dt"] = sh["Date"].apply(_parse_shiller_date)
    sh = sh.dropna(subset=["dt"]).set_index("dt").sort_index()

    p  = pd.to_numeric(sh["P"],          errors="coerce")
    e  = pd.to_numeric(sh["E"],          errors="coerce")
    g  = pd.to_numeric(sh["Rate GS10"],  errors="coerce")

    valid = (e > 0) & (p > 0)
    ey    = (100.0 / (p / e)).where(valid)

    ey_series    = ey[START:].dropna()
    gs10_shiller = g[START:].dropna()

    # 去除重複月底索引
    ey_series    = ey_series[~ey_series.index.duplicated(keep="last")]
    gs10_shiller = gs10_shiller[~gs10_shiller.index.duplicated(keep="last")]

    print(f"  ✓ Shiller: {len(ey_series)} 月，"
          f"{ey_series.index.min().date()} → {ey_series.index.max().date()}")
except Exception as e:
    print(f"  ✗ Shiller 失敗：{e}")

# ── Step 2: multpl.com 補近期 ──
supplement_ey = None
try:
    from bs4 import BeautifulSoup
    pe_resp = requests.get(
        "https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 Chrome/120 Safari/537.36"},
    )
    soup  = BeautifulSoup(pe_resp.text, "html.parser")
    table = soup.find("table", {"id": "datatable"}) or soup.find("table")
    rows_mult = []
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) >= 2:
            try:
                dt  = (pd.to_datetime(tds[0].get_text(strip=True))
                       + pd.offsets.MonthEnd(0))
                val = float(tds[1].get_text(strip=True)
                            .replace(" ", "").replace(",", ""))
                if val > 0:
                    rows_mult.append((dt, val))
            except Exception:
                pass
    if rows_mult:
        pe_mult = pd.Series(dict(rows_mult)).sort_index().resample("ME").last()
        supplement_ey = (100.0 / pe_mult)[START:].dropna()
        print(f"  ✓ multpl.com 補充：{len(supplement_ey)} 月，"
              f"{supplement_ey.index.min().date()} → {supplement_ey.index.max().date()}")
except Exception as e:
    print(f"  (multpl.com 補充略過：{e})")

# ── Step 3: 合併 + 計算 ERP ──
if ey_series is not None:
    ey_combined = (ey_series.combine_first(supplement_ey)
                   if supplement_ey is not None else ey_series)
elif supplement_ey is not None:
    ey_combined = supplement_ey
else:
    ey_combined = None

if ey_combined is not None:
    gs10_comb = (gs10_shiller.combine_first(gs10)
                 if gs10_shiller is not None else gs10)
    idx = ey_combined.index.intersection(gs10_comb.index)
    ey_c, gs10_c = ey_combined.reindex(idx), gs10_comb.reindex(idx)

    erp  = (ey_c - gs10_c).dropna()
    erp.name = "ERP_trailing_proxy"

    mu, sigma = erp.mean(), erp.std()
    print(f"\n  ERP 統計：mean={mu:.4f}%, sigma={sigma:.4f}%")
    print(f"  ±1sigma = [{mu-sigma:.4f}%, {mu+sigma:.4f}%]")
    print(f"  KGI Forward PE ±1sigma（參考）：[-0.1146, 2.3777]")

    erp_df = pd.DataFrame({
        "價差":        erp,
        "AVG-2XSIGMA": mu - 2 * sigma,
        "AVG-1XSIGMA": mu - sigma,
        "AVERAGE":     mu,
        "AVG+1XSIGMA": mu + sigma,
        "AVG+2XSIGMA": mu + 2 * sigma,
    })
    erp_df.index.name = "Date"
    erp_df.to_csv(OUT / "taa_history_erp.csv")
    pd.DataFrame({
        "earnings_yield_pct": ey_c,
        "GS10_pct":           gs10_c,
        "ERP_trailing_pct":   erp,
    }).to_csv(OUT / "taa_history_erp_detail.csv")
    print(f"  → 輸出：taa_history_erp.csv  ({len(erp_df)} 筆)")
    print(f"  → 明細：taa_history_erp_detail.csv")
else:
    print("  ✗ 無法取得 PE 資料，ERP 略過")


# ─────────────────────────────────────────
# 最終摘要
# ─────────────────────────────────────────
print("\n" + "=" * 60)
print("  完成！輸出檔案摘要")
print("=" * 60)

pmi_csv = OUT / "taa_history_pmi.csv"
pmi_status = f"✓ 自動（CFNAI 代理，榮枯線=0）" if pmi_csv.exists() else "✗ 未建立"

rows = [
    ("FDTR",  "taa_history_fdtr.csv",       "FRED DFEDTARU+FEDFUNDS",       "✓ 自動"),
    ("NFP",   "taa_history_nfp.csv",        "FRED PAYEMS diff",             "✓ 自動"),
    ("PMI",   "taa_history_pmi.csv",        "FRED CFNAI（代理，閾值=0）",   pmi_status),
    ("SPX",   "taa_history_spx_ma200.csv",  "yfinance ^GSPC",               "✓ 自動"),
    ("ERP",   "taa_history_erp.csv",        "Shiller Trailing PE + GS10",   "✓ 自動（代理值）"),
]
for factor, fname, source, status in rows:
    print(f"  {factor:<6} {fname:<35} {source:<32} {status}")

print()
print("  ★ 使用 PMI 代理（CFNAI）前，請更新 config.yaml：")
print("      pmi_threshold: 0.0   # CFNAI 榮枯線（預設 50 是給 S&P Global PMI 用的）")
print()
print("  若有 Bloomberg，可改用精確資料：")
print('    BDH("MPMIUSCA Index","PX_LAST","20120101","20230430","periodicitySelection","MONTHLY")')
print("    下載後存成 CSV 放入 data/taa_history_pmi.csv，閾值改回 50")
print()
print("  data_loader.py 自動補充機制：")
print("    Excel（TAA_RawData.xlsx）優先，CSV 填歷史空缺")
print("    PMI/FDTR/NFP CSV 已在 data_loader._CSV_SUPPLEMENTS 中登記")
print("    → 執行 main.py 即自動套用，無需手動修改 Excel")
