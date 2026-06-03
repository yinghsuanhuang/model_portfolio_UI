# 維運操作手冊 (Operations & Maintenance Guide)

> 涵蓋日常資料更新流程、TAA/SAA 參數調整指引、新增/移除資產、常見錯誤排查，以及環境維護。

---

## 目錄

1. [日常資料更新流程](#1-日常資料更新流程)
2. [回測參數調整指引](#2-回測參數調整指引)
3. [TAA 訊號參數調整](#3-taa-訊號參數調整)
4. [新增 / 移除資產](#4-新增--移除資產)
5. [效能與穩定性監控](#5-效能與穩定性監控)
6. [常見錯誤與排查](#6-常見錯誤與排查)
7. [輸出結果驗證](#7-輸出結果驗證)
8. [環境維護](#8-環境維護)

---

## 1. 日常資料更新流程

### 1.1 更新 SAA_RawData.xlsx（每月底）

**資料位置：** `data/SAA_RawData.xlsx`

更新步驟：

1. 在各股票指數工作表（SPX INDEX、SXXP INDEX 等）新增最新月底列，補齊 `Price`、`近12個月每股盈餘`、`股利率12個月殖利率-毛額`、`BEst本益比` 欄位
2. 在 RETURN 工作表新增最新月底列，補齊各資產月報酬率及債券 YTM/Duration 欄位
3. 在 MXWO_LEGATRUU_LG30TRUU INDEX 工作表新增 Benchmark 月底收盤
4. 存檔後執行資料品質檢查：
   ```bash
   python debug_data_quality.py
   ```
5. 確認無 NaN 警告後，更新 `config.yaml` 的 `backtest_end`：
   ```yaml
   dates:
     backtest_end: "2025-11-30"   # 改為最新月份末
   ```

### 1.2 更新 TAA_RawData.xlsx（每月底）

**資料位置：** `data/TAA_RawData.xlsx`

更新步驟：

1. **總體面因子**工作表：新增最新月底列，補齊 `NAPMALL Index`（PMI）、`NFP TCH Index`（非農就業千人）、`FDTR Index`（聯邦基金利率）
2. **市場面因子**工作表：補齊最新日期的 SPX 收盤價與 200 日均線（可日頻，系統自動取月底）
3. **評價面因子**工作表：補齊最新日期的 ERP 價差、`AVG+1XSIGMA`、`AVG-1XSIGMA`
4. 存檔後，在 UI 側邊欄上傳新檔或重啟 Streamlit 驗證訊號是否正確更新

**CSV 歷史補充（可選）：**

若 Excel 早期歷史不完整，`data/` 目錄下的 `taa_history_fdtr.csv`、`taa_history_nfp.csv`、`taa_history_pmi.csv` 會自動補充缺失月份（Excel 優先）。執行以下腳本可從 FRED 等公開來源更新：
```bash
python data/fetch_taa_history.py
```

### 1.3 SAA_RawData.xlsx 欄位格式規範

| 工作表類型 | 必要欄位 | 格式說明 |
|---|---|---|
| 股票指數（SPX INDEX 等） | `Price`、`近12個月每股盈餘`、`股利率12個月殖利率-毛額`、`BEst本益比` | 兩行表頭（row 1 代碼, row 2 名稱）；日期欄名為 `Date` |
| RETURN 工作表 | 各資產月報酬率或收盤價 + 債券 `YTM`/`OAD`（Duration）欄位 | 兩行表頭，date index 為 `Date` |
| Benchmark 工作表 | 三欄月底收盤（對應 `benchmark_cols` 順序） | 兩行表頭 |

> 欄位名稱大小寫須完全符合 `engine/data_loader.py` 中 `RETURN_COL_MAP` / `MARKET_COL_MAP` 的定義。若更換欄名，須同步修改 `data_loader.py`。

---

## 2. 回測參數調整指引

### 2.1 核心參數速查表

| 參數 | `config.yaml` 路徑 | 建議範圍 | 影響說明 |
|---|---|---|---|
| `lookback_months` | `risk.lookback_months` | 24–60 | 共變異數估計回顧期；過短不穩定，過長對近期市況不敏感 |
| `rolling_years` | `return_model.rolling_years` | 3–7 | EPS 成長率計算窗口 |
| `upper` | `constraints.upper` | 0.2–0.5 | 單一資產上限；過低導致強制分散 |
| `stock_type_limit` | `constraints.stock_type_limit` | 0.0–0.8 | 股票類總上限 |
| `bond_type_floor` | `constraints.bond_type_floor` | 0.0–1.0 | 債券類總下限；設太高在股票強勢期可能限制績效 |
| `l2_gamma` | `optimizer.l2_gamma` | 0.05–0.5 | L2 正則強度；過大使權重趨向等權 |
| `risk_aversion` | `optimizer.risk_aversion` | 1.0–5.0 | utility 模式；越大越保守 |
| `trading_cost_bps` | `backtest.trading_cost_bps` | 0–30 | 0 為理想狀況，實際可設 5–15 bps |

### 2.2 各投資人類型建議參數

#### 積極型（Aggressive）
```yaml
optimizer:
  objective: "sortino"
  l2_gamma: 0.1
constraints:
  upper: 0.5
  stock_type_limit: 0.7
  bond_type_floor: 0.2
risk:
  lookback_months: 36
```

#### 成長型（Growth）
```yaml
optimizer:
  objective: "sharpe"
  l2_gamma: 0.1
constraints:
  upper: 0.2
  stock_type_limit: 0.6
  bond_type_floor: 0.4
risk:
  lookback_months: 36
```

#### 穩健型（Balanced）
```yaml
optimizer:
  objective: "utility"
  l2_gamma: 0.2
  risk_aversion: 2.0
constraints:
  upper: 0.2
  stock_type_limit: 0.4
  bond_type_floor: 0.6
universe:
  industry_list: []              # 排除產業
risk:
  lookback_months: 36
```

#### 保守型（Conservative）
```yaml
optimizer:
  objective: "min_variance"
  l2_gamma: 0.1
constraints:
  upper: 1.0
  stock_type_limit: 0.0
  bond_type_floor: 1.0
  asset_upper:
    非投資級債: 0.2
universe:
  market_list: []
  industry_list: []
  bond_list: ["投資級債", "非投資級債"]
```

### 2.3 再平衡頻率選擇指引

| 頻率 | 代碼 | 適用情境 | 注意事項 |
|---|---|---|---|
| 月再平衡 | `M` | 測試模型敏感度 | 交易成本高，實務不建議 |
| 季再平衡 | `Q` | **預設推薦** | 兼顧及時性與成本 |
| 年再平衡 | `A` | 長期配置 | 對短期市場變化反應慢 |
| 半年（6/12月） | `2Q-DEC` | 與財報季對齊 | 適合基本面驅動策略 |

---

## 3. TAA 訊號參數調整

### 3.1 訊號門檻設定

| 參數 | `config.yaml` 路徑 | 預設值 | 說明 |
|---|---|---|---|
| `pmi_threshold` | `taa.pmi_threshold` | 50 | PMI 榮枯線；使用 OECD CLI 代理時需改為 100 |
| `nfp_threshold` | `taa.nfp_threshold` | 50 | 非農就業門檻（千人）；景氣低迷期可降低至 0–30 |

兩個門檻值也可在 UI 側邊欄的 TAA 設定面板中即時覆寫，無需改 config。

### 3.2 評價面乘數調整

```yaml
taa:
  valuation_multipliers:
    plus_1: 1.00   # ERP > +1σ（估值便宜）：使用全額 X
    zero:   0.75   # ERP ±1σ（估值正常）：使用 75% X
    minus_1: 0.50  # ERP < -1σ（估值昂貴）：使用 50% X
```

- 若希望評價面影響更大，可拉大 `plus_1` 與 `minus_1` 之間的差距（如 1.0 / 0.5 / 0.0）
- 若希望弱化評價面影響，縮小差距或全部設為 1.0（乘數固定）

### 3.3 最大調整幅度 X 設定

```yaml
taa:
  profile_max_adjust:
    積極型投資人: 0.10   # ±10% 股債比調整
    成長型投資人: 0.08
    穩健型投資人: 0.06
    保守型投資人: 0.00   # 0 表示該類型不啟用 TAA
```

X 值越大，TAA 對 SAA 的影響越強。建議參考歷史回測中 `taa_signals.csv` 的 `delta_x` 分佈，確認調整幅度在合理範圍。

### 3.4 meeting_flag 處理說明

`meeting_flag = True` 代表總體面與市場面方向相反（例如總體偏多但 SPX 跌破 200MA），表示訊號存在衝突。

**建議處理方式：**
- UI 中啟用「最終期覆核」功能，可手動決定 `direction` 和 `delta_x`
- 或調低當期 X（在 UI 滑桿上降低幅度），採保守立場等待市場確認

---

## 4. 新增 / 移除資產

### 4.1 新增股票市場

1. 在 `SAA_RawData.xlsx` 新增對應工作表（命名規則：`XXX INDEX`），包含 `Price`、基本面欄位
2. 在 `config.yaml` 的 `universe.market_list` 加入新 Ticker：
   ```yaml
   universe:
     market_list:
       - "SPX Index"
       - "NEW_INDEX"    # 新增的 Bloomberg Ticker
   ```
3. 執行測試：
   ```bash
   python debug_data_quality.py
   ```

### 4.2 新增債券類型

1. 在 `SAA_RawData.xlsx` 的 RETURN 工作表新增 YTM、Duration、Price 欄位
2. 更新 `RETURN_COL_MAP`（`engine/data_loader.py`）加入欄位映射
3. 在 `config.yaml` 的 `universe.bond_list` 新增：
   ```yaml
   bond_list:
     - "投資級債"
     - "新債券類型"
   ```
4. 若需要個別上限，在 `constraints.asset_upper` 新增：
   ```yaml
   constraints:
     asset_upper:
       "新債券類型": 0.3
   ```

### 4.3 移除資產

1. 從 `config.yaml` 的對應 `*_list` 中移除資產名稱
2. 對應 Excel 欄位可保留（不影響運算）
3. 重新執行 `python main.py` 確認無錯誤

> 移除資產後，歷史 `outputs/weights.csv` 仍包含舊欄位，不影響新一輪執行，但比較分析時須注意欄位對齊。

### 4.4 修改 Benchmark

Benchmark 欄位對應 `SAA_RawData.xlsx` 中 MXWO_LEGATRUU_LG30TRUU INDEX 工作表的欄位順序。

```yaml
universe:
  benchmark_cols:
    - "新指數1_Ticker"
    - "新指數2_Ticker"
```

同時需在 `main.py` 的 `run_ui_pipeline()` 修改 60/40 固定權重配比（目前為 `[0.6, 0.2, 0.2]`）。

---

## 5. 效能與穩定性監控

### 5.1 回測執行時間參考

| 條件 | 預估時間 |
|---|---|
| 回測期間 10 年、9 個資產 | ~15–30 秒 |
| 回測期間 15 年、9 個資產 | ~30–60 秒 |
| 回測期間 15 年、15 個資產 | ~60–120 秒 |

> 瓶頸通常在 `build_expected_return()` 的每月呼叫。若需加速，可考慮預先批次計算所有月份的 μ 值。

### 5.2 最佳化求解成功率監控

若某月份求解失敗（`Optimization failed`），系統 fallback 至等權重。建議執行後檢查 `outputs/weights.csv`：

```python
import pandas as pd
w = pd.read_csv("outputs/weights.csv", index_col=0)
fallback_mask = (w.std(axis=1) < 0.001)
print(f"疑似 fallback 等權的期數：{fallback_mask.sum()}")
```

### 5.3 TAA 訊號品質確認

執行後可查閱 `outputs/taa_signals.csv` 確認：

```python
import pandas as pd
sig = pd.read_csv("outputs/taa_signals.csv", index_col=0)
print(sig[["direction", "multiplier", "delta_x", "meeting_flag"]].tail(12))
print(f"有調整的月份：{(sig['delta_x'] != 0).sum()}/{len(sig)}")
print(f"meeting_flag 觸發次數：{sig['meeting_flag'].sum()}")
```

### 5.4 資料品質檢查清單

每次更新資料後執行：
```bash
python debug_data_quality.py
```

手動確認項目：
- [ ] 各資產月報酬率不含大量 NaN（允許少量在資料起始期）
- [ ] `EPS`、`PE` 無負值或極端值（> 100x PE 需確認）
- [ ] `YTM` 在合理範圍（0%–20%）
- [ ] `Duration` 在合理範圍（1–20 年）
- [ ] 日期索引連續無跳月
- [ ] TAA 三張工作表的最新日期已對齊至本月底

---

## 6. 常見錯誤與排查

### 6.1 `KeyError: 'XXX Index'` 或 `Sheet not found`

**原因：** `config.yaml` 中的資產名稱與 Excel 工作表名稱不一致

**排查：**
```python
import pandas as pd
xl = pd.ExcelFile("data/SAA_RawData.xlsx")
print(xl.sheet_names)
```

確認名稱（含空格、大小寫）完全一致。

---

### 6.2 `Optimization problem is infeasible`

**可能原因與解法：**

| 原因 | 解法 |
|---|---|
| `upper` 過小 + 資產過多 | 提高 `upper` 或減少資產數量 |
| `stock_type_limit` 過低 | 至少設 0.3 以上（否則多股票時無可行解） |
| `bond_type_floor` 過高 | 降低 `bond_type_floor`；下限不可超過可配置債券資產的上限總和 |
| 某月份所有 μ 為負 | 正常（熊市期），系統 fallback 等權 |
| 保守型含空的 market_list 但 stock_type_limit > 0 | 確認清空資產時同步設 `stock_type_limit: 0.0` |

---

### 6.3 `ValueError: returns_df 必須是月頻`

**原因：** 輸入 `returns_df` 的 DatetimeIndex 不是月底（month-end）格式

**排查：**
```python
import pandas as pd
r = pd.read_csv("outputs/returns.csv", index_col=0, parse_dates=True)
print(r.index[:5])   # 確認是否為月底日期，如 2012-01-31
```

若中間有跳月，需補齊缺失月份。

---

### 6.4 Streamlit 頁面修改後顯示舊結果

**原因：** Streamlit 快取機制（`@st.cache_data`）

**解法：** 點擊瀏覽器上方「⟳」清除快取，或終端機 `Ctrl+C` 後重啟：
```bash
streamlit run ui/app.py
```

---

### 6.5 `ModuleNotFoundError: No module named 'engine'`

**原因：** 在子目錄執行，找不到 `engine` 模組

**正確作法：**
```bash
# 從根目錄執行（正確）
cd /path/to/model_portfolio
streamlit run ui/app.py

# 不要這樣做（錯誤）
cd ui && streamlit run app.py
```

---

### 6.6 TAA_RawData.xlsx 工作表讀取失敗

**原因：** 工作表名稱不符合預期（`engine/data_loader.py` 使用精確名稱比對）

預期工作表名稱：`總體面因子`、`市場面因子`、`評價面因子`

**排查：**
```python
import pandas as pd
xl = pd.ExcelFile("data/TAA_RawData.xlsx")
print(xl.sheet_names)
```

---

### 6.7 PyPortfolioOpt / cvxpy 版本不相容

**解法：**
```bash
pip install --upgrade PyPortfolioOpt cvxpy
python -c "import pypfopt; print(pypfopt.__version__)"
python -c "import cvxpy; print(cvxpy.__version__)"
```

---

## 7. 輸出結果驗證

### 7.1 快速驗證腳本

```python
import pandas as pd

# 1. 確認 SAA 權重之和為 1
w = pd.read_csv("outputs/weights.csv", index_col=0)
assert (w.sum(axis=1) - 1.0).abs().max() < 0.01, "SAA 權重之和不為 1！"
print("✅ SAA 權重和：OK")

# 2. 確認無負數權重
assert (w < -0.001).sum().sum() == 0, "存在負數權重！"
print("✅ 無負數權重：OK")

# 3. 確認 SAA NAV 終值合理
nav = pd.read_csv("outputs/nav_Q.csv", index_col=0).squeeze()
assert nav.iloc[-1] > 0 and not pd.isna(nav.iloc[-1]), "NAV 終值異常！"
print(f"✅ SAA NAV 終值：{nav.iloc[-1]:.4f}")

# 4. 確認 TAA 輸出（若有）
import os
if os.path.exists("outputs/taa_signals.csv"):
    sig = pd.read_csv("outputs/taa_signals.csv", index_col=0)
    assert sig["delta_x"].notna().all(), "TAA delta_x 含 NaN！"
    print(f"✅ TAA 訊號：{(sig['delta_x'] != 0).sum()}/{len(sig)} 個月有調整")
```

### 7.2 績效合理性參考範圍（2012–2025 回測期間）

| 指標 | 需確認（偏低） | 合理範圍 | 需確認（偏高） |
|---|---|---|---|
| CAGR | < 2% | 4%–12% | > 20%（可能有前視偏差） |
| Sharpe | < 0.3 | 0.4–1.2 | > 2.0 |
| Sortino | < 0.4 | 0.5–2.0 | > 3.0 |
| MDD | 超過 -50% | -15% 至 -35% | 優於 -10%（可能過度擬合） |
| Calmar | < 0.2 | 0.2–0.5 | — |

---

## 8. 環境維護

### 8.1 定期更新套件

建議每季確認版本：
```bash
pip list | grep -E "pandas|numpy|PyPortfolioOpt|cvxpy|streamlit"
```

升級（注意可能有 breaking changes）：
```bash
pip install --upgrade pandas numpy PyPortfolioOpt cvxpy streamlit
```

### 8.2 虛擬環境重建

若環境損壞或需在新機器部署：
```bash
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

更新 `requirements.txt`（加入新套件後）：
```bash
pip freeze | grep -v " @ " > requirements.txt
```

### 8.3 Git 版控規範

以下檔案已列入 `.gitignore`，**不應納入版控**：
- `data/` — 原始 Excel 資料（含機密財務數據）
- `outputs/` — 回測產出（可重現）
- `venv/` — 虛擬環境
- `.env` — API Keys

**應納入版控的檔案：**
- `config.yaml`
- `engine/*.py`
- `ui/app.py`
- `main.py`、`report_builder.py`、`preview_report.py`
- `requirements.txt`
- `README.md`、`OPERATIONS.md`

### 8.4 config.yaml 版本管理建議

若需為不同客戶或場景維護不同設定：

```
config.yaml              # 預設（季再平衡、sortino、積極型）
config_conservative.yaml # 保守型專用
config_growth.yaml       # 成長型專用
```

CLI 執行時指定：
```bash
python -c "
from engine.config import load_config
from main import run_full_pipeline_markowitz, run_ui_pipeline
cfg = load_config('config_conservative.yaml')
# ...
"
```

---

## 附錄：程式碼修改指引

### 新增最佳化目標函數

在 `engine/optimizer.py` 的 `solve_weights()` 函式的 `if/elif` 區塊新增：
```python
elif objective == "new_objective":
    ef.new_objective_method(...)
    weights = ef.clean_weights()
```
並在 `ui/app.py` 的 `obj_options` 和 `obj_map` 中新增對應選項。

### 新增績效指標

在 `engine/backtest.py` 的 `backtest_dynamic_weights_monthly()` 函式中，於 `stats` dict 新增：
```python
stats = {
    ...
    "new_metric": float(new_value),
}
```
並在 `ui/app.py` 的績效表 `rows.append(...)` 中新增對應欄位。
