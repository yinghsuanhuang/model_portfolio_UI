
# PMI 取得指南
============================================================
你的模型使用的是「標普全球美國綜合 PMI」(MPMIUSCA Index)。
這是 S&P Global（前 IHS Markit）的付費資料，非 FRED 公開系列。

以下提供三個方案：

─────────────────────────────────────────
方案 A（最準確）：Bloomberg 直接拉長歷史
─────────────────────────────────────────
若你有 Bloomberg 存取權限：

  在 Bloomberg Terminal 執行：
    {MPMIUSCA Index} → Historical Data → 起始日 2010-01-01

  或用 BDH 函數（Excel / Python blpapi）：
    BDH("MPMIUSCA Index", "PX_LAST", "20100101", "today")

  輸出後存成 CSV，格式與現有 TAA_RawData.xlsx 相同即可。

─────────────────────────────────────────
方案 B（免費替代）：ISM 製造業 PMI
─────────────────────────────────────────
ISM 製造業 PMI 與 S&P Global PMI 高度相關（相關係數通常 > 0.92）。
榮枯線同樣是 50，動能邏輯完全適用。

✦ 手動下載（免費）：
  網址：https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/pmi/
  → Download Historical Data → CSV

✦ DBnomics（免費，多來源 PMI）：
  網址：https://db.nomics.world/ISM/pmi
  可用 dbnomics Python 套件：pip install dbnomics
  ```python
  from dbnomics import fetch_series
  pmi = fetch_series("ISM/pmi/MAN_PMI")
  ```

─────────────────────────────────────────
方案 C（OECD CLI 代理，自動化）
─────────────────────────────────────────
若上述皆不可行，可用 OECD 複合領先指標作為 PMI 代理。
相關性約 0.75-0.85，較差但仍有方向性參考價值。

FRED 系列：USALORSGPNOSTSAM
（USA: OECD Composite Leading Indicator, Normalised）

```python
from io import StringIO
import requests, pandas as pd

def fred_csv(sid):
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2010-01-01'
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    df = pd.read_csv(StringIO(r.text), index_col=0, parse_dates=True)
    return df.iloc[:, 0]

oecd_cli = fred_csv('USALORSGPNOSTSAM')
# 需校正閾值：CLI 以 100 為榮枯線，而非 50
# 建議在 config.yaml 中調整 pmi_threshold: 100
```

─────────────────────────────────────────
建議優先順序
─────────────────────────────────────────
1. 若有 Bloomberg → 方案 A（同指標，最準）
2. 若無 Bloomberg → 方案 B ISM（免費，相關高）
3. 完全自動化 → 方案 C OECD CLI（需調整閾值）

注意：若改用 ISM PMI，config.yaml 不需改變（閾值仍是 50）。
