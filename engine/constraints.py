from __future__ import annotations

def build_stock_type_indices(asset_names: list[str], stock_type_names: list[str]) -> list[int]:
    return [asset_names.index(n) for n in stock_type_names if n in asset_names]
