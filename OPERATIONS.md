# 維運操作手冊 (Operations & Maintenance Guide)

> 本文件涵蓋日常資料更新流程、參數調整指引、常見問題排查，以及新資產擴充方式。

---

## 目錄

1. [日常資料更新流程](#1-日常資料更新流程)
2. [回測參數調整指引](#2-回測參數調整指引)
3. [新增 / 移除資產](#3-新增--移除資產)
4. [效能與穩定性監控](#4-效能與穩定性監控)
5. [常見錯誤與排查](#5-常見錯誤與排查)
6. [輸出結果驗證](#6-輸出結果驗證)
7. [環境維護](#7-環境維護)

---

## 1. 日常資料更新流程

### 1.1 更新 Excel 資料來源

**資料檔案位置：** `data/` 資料夾

| 檔案 | 更新頻率 | 更新內容 |
|---|---|---|
| `指數預期報酬率-1.xlsx` | 月底 | 各指數最新 EPS、殖利率、PE、YTM、Duration |
| `模組報酬率.xlsx` | 月底 | 各資產最新月報酬率或收盤價格指數 |

**更新步驟：**

1. 在 Excel 中新增最新月份的資料列（格式同現有資料）
2. 確認日期欄位為月底日期（例如 `2025-11-30`）
3. 存檔後，執行資料品質檢查：

   ```bash
   python debug_data_quality.py
   ```

4. 確認無 `NaN` 警告後，更新 `config.yaml` 的 `backtest_end`：

   ```yaml
   dates:
     backtest_end: "2025-11-30"   # 改為最新月份末
   ```

5. 重新執行回測：

   ```bash
   python main.py
   ```

### 1.2 Excel 欄位格式規範

`指數預期報酬率-1.xlsx` 各 Sheet 欄位對應：

| 市場/資產類型 | 必要欄位 | 說明 |
|---|---|---|
| 股票市場（SPX、SXXP 等） | `Price`、`EPS`、`DY`（殖利率）、`PE` | Price 為收盤指數；DY 為年化殖利率（%） |
| 債券（投資級債等） | `Price`、`YTM`、`Duration` | YTM 為年化（%）；Duration 為修正存續期間（年） |
| 產業 | `Price` | 用於 CAPM Beta 計算 |

> **注意：** 欄位名稱大小寫須完全符合 `engine/data_loader.py` 中的讀取邏輯。若更換資料來源或調整欄位名稱，須同步修改 `data_loader.py`。

---

## 2. 回測參數調整指引

### 2.1 核心參數速查表

| 參數 | 路徑 | 建議範圍 | 影響說明 |
|---|---|---|---|
| `lookback_months` | `risk.lookback_months` | 24–60 | 共變異數估計回顧期；過短不穩定，過長對近期市況不敏感 |
| `rolling_years` | `return_model.rolling_years` | 3–7 | EPS 成長率計算窗口；縮短反應近期趨勢，拉長降低雜訊 |
| `upper` | `constraints.upper` | 0.2–0.5 | 單一資產上限；過低導致強制分散（可能降低 Sharpe） |
| `stock_type_limit` | `constraints.stock_type_limit` | 0.4–0.8 | 股票類總上限；決定整體股債比 |
| `l2_gamma` | `optimizer.l2_gamma` | 0.05–0.5 | L2 正則強度；過大使權重趨向等權，過小可能極端集中 |
| `risk_aversion` | `optimizer.risk_aversion` | 1.0–5.0 | 效用函數風險趨避（utility 模式）；越大越保守 |
| `trading_cost_bps` | `backtest.trading_cost_bps` | 0–30 | 交易成本估計；0 為理想狀況，實際可設 5–15 bps |

### 2.2 各投資人類型建議參數

#### 積極型（Aggressive）
```yaml
optimizer:
  objective: "sortino"
  l2_gamma: 0.1
constraints:
  upper: 0.5
  stock_type_limit: 0.7
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

## 3. 新增 / 移除資產

### 3.1 新增股票市場

**步驟：**

1. 在 `指數預期報酬率-1.xlsx` 中新增一個 Sheet，包含 `Price`、`EPS`、`DY`、`PE` 欄位

2. 在 `模組報酬率.xlsx` 中新增對應的歷史價格欄位

3. 在 `config.yaml` 的 `universe.market_list` 加入新 Ticker：
   ```yaml
   universe:
     market_list:
       - "SPX Index"
       - "SXXP Index"
       - "NEW_INDEX"    # 新增的 Bloomberg Ticker
   ```

4. 確認 `engine/data_loader.py` 的 `load_market_sheet()` 能正確讀取新 Sheet

5. 執行測試：
   ```bash
   python debug_data_quality.py
   ```

### 3.2 新增債券類型

1. 在 `指數預期報酬率-1.xlsx` 新增包含 `YTM`、`Duration`、`Price` 的 Sheet

2. 在 `config.yaml` 的 `universe.bond_list` 新增：
   ```yaml
   universe:
     bond_list:
       - "投資級債"
       - "非投資級債"
       - "新興市場債"
       - "新債券類型"    # 新增
   ```

3. 確認 `engine/data_loader.py` 的 `load_bond_and_industry()` 讀取邏輯能對應

4. 若新債券需要特殊上限限制，可在 `config.yaml` 新增：
   ```yaml
   constraints:
     asset_upper:
       "新債券類型": 0.3    # 此債券最高 30%
   ```

### 3.3 移除資產

1. 從 `config.yaml` 的對應 `*_list` 中移除資產名稱
2. 對應 Excel Sheet 可保留（不影響運算），或直接刪除
3. 重新執行 `python main.py` 確認無錯誤

> **注意：** 移除資產後，若歷史 `outputs/weights.csv` 仍包含舊欄位，不影響新一輪執行，但比較分析時須注意欄位對齊。

### 3.4 修改 Benchmark

目前 60/40 基準的欄位設定在 `universe.benchmark_cols`，對應 `模組報酬率.xlsx` 中的欄位名稱。

若要更換 Benchmark：
```yaml
universe:
  benchmark_cols:
    - "新基準1_Ticker"
    - "新基準2_Ticker"
```

同時需在 `main.py` 的 `run_ui_pipeline()` 中修改 60/40 固定權重配比（目前為 `[0.6, 0.2, 0.2]`）。

---

## 4. 效能與穩定性監控

### 4.1 回測執行時間參考

| 條件 | 預估時間 |
|---|---|
| 回測期間 10 年、9 個資產 | ~15–30 秒 |
| 回測期間 15 年、9 個資產 | ~30–60 秒 |
| 回測期間 15 年、15 個資產 | ~60–120 秒 |

> 瓶頸通常在 `build_expected_return()` 的每月呼叫。若需加速，可考慮預先計算所有月份的 μ 值後再批次求解。

### 4.2 最佳化求解成功率監控

在 `engine/optimizer.py` 的 `solve_weights()` 中，若某月份求解失敗（`Optimization failed`），系統會 fallback 至等權重。

建議執行後檢查 `outputs/weights.csv`，確認是否有長時間等權重的連續期間（可能代表某段時間最佳化持續失敗）：

```python
import pandas as pd
w = pd.read_csv("outputs/weights.csv", index_col=0)
# 若某行所有資產權重相同，可能是 fallback 等權
fallback_mask = (w.std(axis=1) < 0.001)
print(f"疑似 fallback 的期數：{fallback_mask.sum()}")
```

### 4.3 資料品質檢查清單

每次更新資料後，執行以下確認：

```bash
python debug_data_quality.py
```

手動確認項目：
- [ ] 各資產月報酬率不含大量 `NaN`（允許少量在資料起始期）
- [ ] `EPS`、`PE` 無負值或極端值（> 100x PE 需確認）
- [ ] `YTM` 在合理範圍（0%–20%）
- [ ] `Duration` 在合理範圍（1–20 年）
- [ ] 日期索引連續無跳月

---

## 5. 常見錯誤與排查

### 5.1 `KeyError: 'XXX Index'`

**現象：** 執行時報 `KeyError`，顯示某 Ticker 名稱

**原因：** `config.yaml` 的 `universe.*_list` 中有資產名稱，但 Excel 中找不到對應 Sheet 或欄位

**排查：**
```python
import pandas as pd
xl = pd.ExcelFile("data/指數預期報酬率-1.xlsx")
print(xl.sheet_names)   # 確認 Sheet 名稱
```

確認 Sheet 名稱與 `config.yaml` 中的資產名稱完全一致（包含空格、大小寫）。

---

### 5.2 `Optimization problem is infeasible`

**現象：** 最佳化無解，Console 顯示 `infeasible` 或 `Optimization failed`

**可能原因與解法：**

| 原因 | 解法 |
|---|---|
| 約束條件過緊（`upper` 太小 + 資產太多） | 提高 `upper`，或減少資產數量 |
| `stock_type_limit` 過低 | 對多數股票市場，至少設 0.3 以上 |
| 某月份所有 μ 為負 | 正常現象（熊市期），系統會 fallback 等權 |
| 保守型含 `market_list: []` 但 `stock_type_limit > 0` | 確認清空資產的同時也將 `stock_type_limit` 設為 0 |

---

### 5.3 `ValueError: returns_df 必須是月頻`

**現象：** 回測引擎報 `periods_per_year` 偵測異常

**原因：** 輸入 `returns_df` 的 DatetimeIndex 日期不是月底（month-end）格式

**排查：**
```python
import pandas as pd
r = pd.read_csv("outputs/returns.csv", index_col=0, parse_dates=True)
print(r.index[:5])   # 確認是否為月底日期，如 2012-01-31
```

若日期格式正確但 `pd.infer_freq` 仍失敗，可能是資料中間有跳月，需補齊缺失月份。

---

### 5.4 `Streamlit` 頁面執行後沒有更新

**現象：** 修改 `config.yaml` 後，Streamlit 顯示舊結果

**原因：** Streamlit 有快取機制（`@st.cache_data`）

**解法：** 點選瀏覽器上方「⟳」清除快取，或在終端機按 `Ctrl+C` 重啟 Streamlit：
```bash
streamlit run ui/app.py
```

---

### 5.5 `ModuleNotFoundError: No module named 'engine'`

**現象：** 在 `ui/` 目錄下直接執行 Python 時找不到 `engine` 模組

**原因：** 需從專案根目錄執行，不能在子目錄執行

**正確作法：**
```bash
# 從根目錄執行（正確）
cd /path/to/model_portfolio
streamlit run ui/app.py

# 不要這樣做（錯誤）
cd ui
streamlit run app.py
```

---

### 5.6 PyPortfolioOpt / cvxpy 版本不相容

**現象：** 最佳化報 `solver_error` 或 `CVXPY version` 警告

**解法：**
```bash
pip install --upgrade PyPortfolioOpt cvxpy
```

確認版本：
```bash
python -c "import pypfopt; print(pypfopt.__version__)"
python -c "import cvxpy; print(cvxpy.__version__)"
```

---

## 6. 輸出結果驗證

### 6.1 快速驗證腳本

執行完整 Pipeline 後，可用以下方式快速確認結果合理性：

```python
import pandas as pd
import json

# 1. 確認權重之和為 1
w = pd.read_csv("outputs/weights.csv", index_col=0)
row_sums = w.sum(axis=1)
assert (row_sums - 1.0).abs().max() < 0.01, "權重之和不為 1！"
print("✅ 權重和：OK")

# 2. 確認無負數權重
assert (w < -0.001).sum().sum() == 0, "存在負數權重（不允許放空）！"
print("✅ 無負數權重：OK")

# 3. 確認 CAGR 在合理範圍
with open("outputs/stats.json") as f:
    stats = json.load(f)
# 注意：stats.json 的結構依 run_all_frequencies_monthly 輸出而定

# 4. 確認 NAV 最終值合理（非 0 或 NaN）
nav = pd.read_csv("outputs/nav_Q.csv", index_col=0).squeeze()
assert nav.iloc[-1] > 0 and not pd.isna(nav.iloc[-1]), "NAV 終值異常！"
print(f"✅ NAV 終值：{nav.iloc[-1]:.4f}")
```

### 6.2 績效合理性參考範圍

以 2012–2025 年回測期間為參考，合理的 Markowitz 策略績效範圍：

| 指標 | 低（需確認） | 合理範圍 | 備註 |
|---|---|---|---|
| CAGR | < 2% | 4%–12% | 視市場環境而定 |
| Sharpe | < 0.3 | 0.4–1.2 | |
| Sortino | < 0.4 | 0.5–2.0 | 通常 > Sharpe |
| MDD | < -50% | -15% 至 -35% | 含 2020 COVID 事件 |
| Calmar | < 0.2 | 0.2–0.5 | |

若結果超出範圍（例如 CAGR > 20% 或 Sharpe > 2.0），建議檢查是否有前視偏差或資料錯誤。

---

## 7. 環境維護

### 7.1 定期更新套件

建議每季確認套件版本，特別是：
```bash
pip list | grep -E "pandas|numpy|PyPortfolioOpt|cvxpy|streamlit"
```

若需升級（注意可能有 breaking changes）：
```bash
pip install --upgrade pandas numpy PyPortfolioOpt cvxpy streamlit
```

### 7.2 虛擬環境重建

若環境損壞或需要在新機器部署：
```bash
# 刪除舊環境
rm -rf .venv

# 重建
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

若要更新 `requirements.txt`（加入新套件後）：
```bash
pip freeze | grep -v " @ " > requirements.txt
```

> **注意：** `pip freeze` 會包含所有套件（含間接依賴），可手動精簡只保留直接依賴套件。

### 7.3 Git 版控規範

以下檔案已列入 `.gitignore`，**不應納入版控**：
- `data/` — 原始 Excel 資料（含機密財務數據）
- `outputs/` — 回測產出（可重現，不需版控）
- `.venv/` — 虛擬環境

**應納入版控的檔案：**
- `config.yaml` — 參數設定
- `engine/*.py` — 核心邏輯
- `ui/app.py` — 介面邏輯
- `main.py` — 主程式
- `requirements.txt` — 套件清單
- `README.md`、`OPERATIONS.md` — 文件

### 7.4 config.yaml 版本管理建議

若需要為不同客戶或場景維護不同設定，建議建立命名設定檔：

```
config.yaml              # 預設（季再平衡、sortino）
config_conservative.yaml # 保守型專用
config_aggressive.yaml   # 積極型專用
```

CLI 執行時指定：
```bash
python -c "
from engine.config import load_config
from main import run_full_pipeline_markowitz, load_all_data
cfg = load_config('config_conservative.yaml')
data = load_all_data(cfg)
# ...
"
```

---

## 附錄：程式碼修改指引

### 新增最佳化目標函數

在 `engine/optimizer.py` 的 `solve_weights()` 函式中，於 `if/elif` 區塊新增：

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
