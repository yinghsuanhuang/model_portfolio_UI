from __future__ import annotations
from pathlib import Path
import pandas as pd
from pandas.tseries.offsets import MonthEnd
import yaml


def _detect_latest_data_month(cfg: dict) -> pd.Timestamp:
    """掃描 SAA_RawData.xlsx 的 RETURN 工作表，回傳最新一筆月底 Timestamp。

    用於 backtest_end: auto。RETURN 工作表是各資產實際月報酬的來源，
    其最後一列即「資料目前更新到的月份」。
    """
    data_dir = Path(cfg["paths"]["data_dir"])
    saa_path = data_dir / cfg["paths"]["saa_raw_xlsx"]
    if not saa_path.exists():
        raise FileNotFoundError(
            f"backtest_end 設為 auto，但找不到資料檔以偵測最新月份：{saa_path}"
        )

    xl = pd.ExcelFile(saa_path)
    norm = {s.strip().lower(): s for s in xl.sheet_names}
    sheet = norm.get("return")
    if sheet is None:
        raise ValueError("backtest_end=auto 偵測失敗：找不到 RETURN 工作表。")

    idx = pd.read_excel(
        saa_path, sheet_name=sheet, header=1, index_col=0, usecols=[0]
    ).index
    idx = pd.to_datetime(idx, errors="coerce").dropna().sort_values()
    if len(idx) == 0:
        raise ValueError("backtest_end=auto 偵測失敗：RETURN 工作表沒有有效日期。")

    return idx[-1] + MonthEnd(0)


def load_config(path: str | Path) -> dict:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # backtest_end 支援 "auto" / 留空：自動偵測資料最新月底並填回具體日期，
    # 讓所有下游消費端（main / UI / report / taa…）一律拿到可解析的日期字串。
    raw_end = cfg.get("dates", {}).get("backtest_end")
    if raw_end is None or str(raw_end).strip().lower() == "auto":
        detected = _detect_latest_data_month(cfg)
        cfg["dates"]["backtest_end"] = detected.strftime("%Y-%m-%d")
        print(f"▶ backtest_end=auto → 自動偵測最新資料月份：{cfg['dates']['backtest_end']}")

    return cfg
