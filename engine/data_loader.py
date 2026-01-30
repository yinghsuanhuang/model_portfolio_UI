from __future__ import annotations
from pathlib import Path
import pandas as pd
from pandas.tseries.offsets import MonthEnd


def _load_and_resample_month_end(df: pd.DataFrame) -> pd.DataFrame:
    """
    統一處理：
    - index 轉成 DatetimeIndex
    - sort
    - resample("M").last()  → 統一成「月頻、取月底」
    - 再補上 MonthEnd(0) 確保是月底
    """
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # 關鍵：全部 resample 成月頻（取該月最後一筆）
    df = df.resample("M").last()

    # 確保 index 都是月末
    df.index = df.index + MonthEnd(0)
    return df


def load_benchmark(expected_return_xlsx: Path, benchmark_cols: list[str]) -> pd.DataFrame:
    df = pd.read_excel(
        expected_return_xlsx,
        sheet_name="Benchmark",
        index_col="Date",
    )
    df = _load_and_resample_month_end(df)
    df.columns = benchmark_cols
    return df


def load_bond_and_industry(module_return_xlsx: Path) -> pd.DataFrame:
    df = pd.read_excel(
        module_return_xlsx,
        sheet_name=0,
        index_col="Date",
    )
    df = _load_and_resample_month_end(df)
    return df


def load_market_sheet(expected_return_xlsx: Path, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(
        expected_return_xlsx,
        sheet_name=sheet_name,
        index_col="Date",
    )
    df = _load_and_resample_month_end(df)

    # 統一欄位命名
    if "最新價  (R3)" in df.columns:
        df = df.rename(columns={"最新價  (R3)": "Price"})

    return df


def load_all_data(config: dict) -> dict:
    data_dir = Path(config["paths"]["data_dir"])
    expected_path = data_dir / config["paths"]["expected_return_xlsx"]
    module_path = data_dir / config["paths"]["module_return_xlsx"]

    benchmark = load_benchmark(expected_path, config["universe"]["benchmark_cols"])
    bond_industry = load_bond_and_industry(module_path)

    return {
        "expected_path": expected_path,
        "module_path": module_path,
        "benchmark": benchmark,
        "bond_industry": bond_industry,
    }
