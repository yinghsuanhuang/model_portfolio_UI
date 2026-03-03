
import pandas as pd
from pathlib import Path

def inspect_excel():
    file_path = "data/模組報酬率.xlsx"
    print(f"Reading: {file_path}")
    
    # Read without header first to see raw structure
    df = pd.read_excel(file_path, sheet_name=0, header=None, nrows=10)
    print("\n--- Raw Top 10 Rows (Sheet 0) ---")
    print(df)
    
    # Try reading with header=0 (default)
    df = pd.read_excel(file_path, sheet_name=0)
    print("\n--- Rows around 2023-09 ---")
    df['Date'] = pd.to_datetime(df['Date'])
    mask = (df['Date'] >= '2023-08-01') & (df['Date'] <= '2023-11-30')
    print(df.loc[mask, ['Date', '投資級債', '非投資級債']])
    
    # Check specific dates if possible (need to parse full file for that, let's limit to head for now)

if __name__ == "__main__":
    inspect_excel()
