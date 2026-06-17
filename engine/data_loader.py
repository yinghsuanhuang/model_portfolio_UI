from __future__ import annotations
import functools
from pathlib import Path
import pandas as pd
from pandas.tseries.offsets import MonthEnd


# ============================================================
# SAA_RawData.xlsx 格式說明
# ------------------------------------------------------------
# - 每張工作表都有「兩行表頭」：
#     row 1 = 欄位代碼（PR005 / RR906 ... 或 S5MATR Index ...）
#     row 2 = 中文/可讀欄位名稱
#   讀取時統一使用 header=1，讓欄名落在第二行
# - 股票工作表（SPX INDEX / SXXP INDEX / ...）：header=1 後為中文欄名
# - Benchmark 工作表（MXWO_LEGATRUU_LG30TRUU INDEX，注意尾端可能有空白）
#   及 RETURN 工作表：header=1 後為英文代碼欄名
# ============================================================


# RETURN 工作表的英文代碼 → 回測引擎內部使用的中文鍵
RETURN_COL_MAP = {
    "S5MATR Index": "原物料",
    "S5HLTH Index": "醫療健護",
    "S5INFT Index": "科技",
    "LEGATRUU Index": "投資級債",
    "LG30TRUU Index": "非投資級債",
    "EMUSTRUU Index": "新興市場債",
    "USGG10YR Index": "10年期公債殖利率",
    "SPX Index": "標普500",
    "LEGATRUU Index YTM": "投資級債YTM",
    "LEGATRUU Index OAD": "投資級債Dur",
    "LG30TRUU Index YTM": "非投資級債YTM",
    "LG30TRUU Index OAD": "非投資級債Dur",
    "EMUSTRUU Index YTM": "新興市場債YTM",
    "EMUSTRUU Index OAD": "新興市場債Dur",
    "BYXYUS Q226 Index": "債券殖利率預估",
}

# RETURN 工作表中「以價格表示」的欄位，需轉成月報酬以對齊舊「Return」工作表行為
RETURN_PRICE_COLS = [
    "原物料", "醫療健護", "科技",
    "投資級債", "非投資級債", "新興市場債",
    "標普500",
]

# 股票工作表欄名 → return_model.py 預期的欄名（保留 (R1)/(R2)/(L2) 後綴）
MARKET_COL_MAP = {
    "最新價": "Price",
    "近12個月每股盈餘": "近12個月每股盈餘  (R2)",
    "股利率12個月殖利率-毛額": "股利率12個月殖利率-毛額  (R1)",
    "BEst每股盈餘": "BEst每股盈餘  (L2)",
    "BEst本益比": "BEst本益比  (L1)",
}


# ============================================================
# 共用工具
# ============================================================

def _to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """
    - index 轉成 DatetimeIndex
    - sort
    - resample("ME").last() → 月頻取月底
    - 確保 index 對齊到月末
    """
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.resample("ME").last()
    df.index = df.index + MonthEnd(0)
    return df


def _find_sheet(xl: pd.ExcelFile, *candidates: str) -> str:
    """從 ExcelFile 取得工作表名稱：去除前後空白且不分大小寫比對。"""
    norm = {s.strip().lower(): s for s in xl.sheet_names}
    for cand in candidates:
        s = norm.get(cand.strip().lower())
        if s is not None:
            return s
    raise KeyError(
        f"Sheet not found. Tried {candidates}, available: {xl.sheet_names}"
    )


def load_monthly_commentary(taa_path: str | Path) -> dict[str, str]:
    """由 TAA_RawData.xlsx 路徑讀取「月報文字」分頁（供報告端在快取缺漏時補讀）。"""
    taa_path = Path(taa_path)
    if not taa_path.exists():
        return {}
    return _load_monthly_commentary(pd.ExcelFile(taa_path), taa_path)


def _load_monthly_commentary(xl: pd.ExcelFile, taa_path: Path) -> dict[str, str]:
    """讀取「月報文字」分頁，回傳 {主題: 內文} 的有序字典。

    分頁格式為兩欄（主題 / 內文），每列一個主題（如美國經濟、美國股市、
    殖利率/Fed、債券看法、匯率）。分頁不存在時回傳空字典（不影響回測）。
    """
    try:
        sheet = _find_sheet(xl, "月報文字")
    except KeyError:
        return {}
    df = pd.read_excel(taa_path, sheet_name=sheet, header=None)
    commentary: dict[str, str] = {}
    for _, row in df.iterrows():
        topic = row.iloc[0]
        body = row.iloc[1] if len(row) > 1 else None
        if pd.isna(topic) or pd.isna(body):
            continue
        topic, body = str(topic).strip(), str(body).strip()
        if topic and body:
            commentary[topic] = body
    return commentary


# ============================================================
# 對外 API
# ============================================================

def load_benchmark(saa_path: Path, benchmark_cols: list[str]) -> pd.DataFrame:
    xl = pd.ExcelFile(saa_path)
    sheet = _find_sheet(xl, "MXWO_LEGATRUU_LG30TRUU INDEX", "Benchmark")
    df = pd.read_excel(saa_path, sheet_name=sheet, header=1, index_col="Date")
    df = _to_monthly(df)

    if len(df.columns) != len(benchmark_cols):
        raise ValueError(
            f"Benchmark sheet has {len(df.columns)} columns "
            f"but config benchmark_cols has {len(benchmark_cols)}. "
            f"sheet cols={list(df.columns)}, config={benchmark_cols}"
        )
    df.columns = benchmark_cols
    return df


def load_bond_and_industry(saa_path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(saa_path)
    sheet = _find_sheet(xl, "RETURN", "Return")
    df = pd.read_excel(saa_path, sheet_name=sheet, header=1, index_col="Date")
    df = _to_monthly(df)
    df = df.rename(columns=RETURN_COL_MAP)

    # 把價格欄位轉成月報酬（對齊舊「Return」工作表的數值含義）
    for c in RETURN_PRICE_COLS:
        if c in df.columns:
            df[c] = df[c].pct_change()
    return df


@functools.lru_cache(maxsize=None)
def _load_market_sheet_cached(saa_path_str: str, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(saa_path_str, sheet_name=sheet_name, header=1, index_col="Date")
    df = _to_monthly(df)
    df = df.rename(columns=MARKET_COL_MAP)
    return df


def load_market_sheet(saa_path: Path, sheet_name: str) -> pd.DataFrame:
    return _load_market_sheet_cached(str(saa_path), sheet_name)


# ============================================================
# TAA_RawData.xlsx
# ------------------------------------------------------------
# 三張工作表（皆兩行表頭，header=1 取第二行、index=Date）：
#   總體面因子：NAPMALL Index / NFP TCH Index / FDTR Index
#   市場面因子：SPX 最新價 / 200 日均線
#   評價面因子：ERP 價差 / ±1σ / ±2σ / 平均
# 市場面與評價面為日頻 → resample 月底；總體面已是月頻
# ============================================================

TAA_MACRO_COL_MAP = {
    "NAPMALL Index": "pmi",    # ISM 美國綜合 PMI（舊檔為 MPMIUSCA Index）
    "NFP TCH Index": "nfp",
    "FDTR Index": "fdtr",
}

# CSV 補充欄位對應（data/ 目錄下，如存在則自動補歷史空缺）
_CSV_SUPPLEMENTS = {
    "fdtr": "taa_history_fdtr.csv",
    "nfp":  "taa_history_nfp.csv",
    "pmi":  "taa_history_pmi.csv",   # 未來 Bloomberg PMI 下載後放此
}


def _supplement_macro(macro: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """
    若 data/ 目錄下有 CSV 補充檔，合併歷史缺失資料。
    Excel 資料永遠優先（combine_first 語義：self 優先，NaN 才用 other）。
    補充資料的 index 可能比 Excel 更早，需先擴展 DataFrame 再填值。
    """
    supplements: dict[str, pd.Series] = {}
    for col, fname in _CSV_SUPPLEMENTS.items():
        csv_path = data_dir / fname
        if not csv_path.exists() or col not in macro.columns:
            continue
        try:
            supp = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            supp = supp.resample("ME").last()
            supp_s = supp.iloc[:, 0].rename(col)
            supplements[col] = supp_s
        except Exception:
            pass

    if not supplements:
        return macro

    # 合併所有補充 Series 的 index，擴展 macro 的行範圍
    all_supp_idx = pd.DatetimeIndex([])
    for s in supplements.values():
        all_supp_idx = all_supp_idx.union(s.index)

    full_idx = macro.index.union(all_supp_idx)
    macro = macro.reindex(full_idx)  # 展開後舊資料保留，新行為 NaN

    for col, supp_s in supplements.items():
        macro[col] = macro[col].combine_first(supp_s)

    return macro


def load_taa_data(config: dict, override_path: str | Path | None = None) -> dict:
    """
    讀取 TAA_RawData.xlsx，回傳月頻對齊後的三個 DataFrame。
    override_path：UI 上傳新檔時傳入該檔路徑。
    """
    if override_path is not None:
        taa_path = Path(override_path)
        data_dir = taa_path.parent
    else:
        data_dir = Path(config["paths"]["data_dir"])
        taa_path = data_dir / config["paths"].get("taa_raw_xlsx", "TAA_RawData.xlsx")

    if not taa_path.exists():
        raise FileNotFoundError(f"TAA raw data file not found: {taa_path}")

    xl = pd.ExcelFile(taa_path)

    # ── 總體面（已月頻）──
    s_macro = _find_sheet(xl, "總體面因子")
    macro = pd.read_excel(taa_path, sheet_name=s_macro, header=1, index_col="Date")
    macro = macro.rename(columns=TAA_MACRO_COL_MAP)
    macro = macro[["pmi", "nfp", "fdtr"]]
    macro = _to_monthly(macro)
    macro = _supplement_macro(macro, data_dir)

    # ── 市場面（日頻 → 月底）──
    s_market = _find_sheet(xl, "市場面因子")
    market = pd.read_excel(taa_path, sheet_name=s_market, header=1, index_col="Date")
    market = market.iloc[:, :2]
    market.columns = ["spx", "ma200"]
    market = _to_monthly(market)

    # ── 評價面（日頻 → 月底）──
    s_val = _find_sheet(xl, "評價面因子")
    val = pd.read_excel(taa_path, sheet_name=s_val, header=1, index_col="Date")
    val = val.rename(columns={
        "價差": "erp",
        "AVG-1XSIGMA": "sigma_minus1",
        "AVG+1XSIGMA": "sigma_plus1",
    })
    val = val[["erp", "sigma_minus1", "sigma_plus1"]]
    val = _to_monthly(val)

    # ── 月報文字（市場觀點，用於 AI 摘要；缺漏不影響回測）──
    commentary = _load_monthly_commentary(xl, taa_path)

    return {
        "taa_path": taa_path,
        "macro": macro,
        "market": market,
        "valuation": val,
        "commentary": commentary,
    }


def load_all_data(config: dict, override_path: str | Path | None = None) -> dict:
    """
    讀取 SAA_RawData.xlsx。
    override_path：若 UI 上傳了新檔，傳入該檔路徑以取代設定檔預設值。
    """
    if override_path is not None:
        saa_path = Path(override_path)
    else:
        data_dir = Path(config["paths"]["data_dir"])
        saa_path = data_dir / config["paths"]["saa_raw_xlsx"]

    if not saa_path.exists():
        raise FileNotFoundError(f"SAA raw data file not found: {saa_path}")

    benchmark = load_benchmark(saa_path, config["universe"]["benchmark_cols"])
    bond_industry = load_bond_and_industry(saa_path)

    return {
        "expected_path": saa_path,   # return_model.load_market_sheet 用此路徑逐張表讀
        "module_path": saa_path,     # 保留欄位以維持下游相容
        "benchmark": benchmark,
        "bond_industry": bond_industry,
    }
