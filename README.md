# 量化模型投組研究平台 (Quantitative Model Portfolio Research Platform)

> 內部量化研究工具，提供前瞻性預期報酬模型、Markowitz 最佳化與滾動回測功能，並透過 Streamlit 互動儀表板支援多種投資人風險偏好配置。

---

## 目錄

- [系統架構](#系統架構)
- [功能特色](#功能特色)
- [環境安裝](#環境安裝)
- [快速開始](#快速開始)
- [設定檔說明](#設定檔說明-configyaml)
- [模型方法論](#模型方法論)
- [輸出檔案說明](#輸出檔案說明)
- [資料來源](#資料來源)
- [常見問題](#常見問題)

---

## 系統架構

```
model_portfolio/
├── config.yaml              # 全域參數設定（唯一設定入口）
├── requirements.txt         # Python 套件清單
├── main.py                  # CLI 入口 & UI 後端 Pipeline
│
├── engine/                  # 核心量化引擎（純計算，無 UI 依賴）
│   ├── config.py            # YAML 設定讀取工具
│   ├── data_loader.py       # 資料讀取與前處理
│   ├── return_model.py      # 前瞻性預期報酬模型
│   ├── risk_model.py        # 共變異數矩陣估計（Ledoit-Wolf）
│   ├── optimizer.py         # 投組最佳化求解器（PyPortfolioOpt）
│   ├── backtest.py          # 滾動回測與績效計算
│   ├── constraints.py       # 最佳化限制條件輔助
│   └── utils.py             # 報酬率計算工具
│
├── ui/
│   └── app.py               # Streamlit Web 儀表板
│
├── data/                    # 原始資料（Excel，不納入版控）
│   ├── 指數預期報酬率-1.xlsx
│   └── 模組報酬率.xlsx
│
└── outputs/                 # 回測產出（CSV / JSON，不納入版控）
    ├── weights.csv
    ├── returns.csv
    ├── nav_Q.csv
    ├── nav_M.csv
    ├── nav_A.csv
    ├── nav_2Q-DEC.csv
    ├── stats.json
    └── summary.csv
```

---

## 功能特色

### 前瞻性預期報酬模型
- **股票市場**：結合 EPS 5 年滾動成長率、12 月平均殖利率、PE 均值回歸調整
- **固定收益**：基於 YTM 與 Duration 的利率敏感度估計
- **產業**：CAPM Beta 動態估計（相對 S&P 500）

### 多目標投組最佳化
| 目標函數 | 說明 | 適用投資人 |
|---|---|---|
| `sortino` | 最大化 Sortino Ratio（下行風險調整） | 積極型 |
| `sharpe` | 最大化 Sharpe Ratio（全波動風險調整） | 成長型 |
| `utility` | 最大化二次效用函數（含風險趨避係數） | 穩健型 |
| `min_variance` | 最小化投組波動度 | 保守型 |

### 動態回測引擎
- 支援 4 種再平衡頻率：`M`（月）、`Q`（季）、`A`（年）、`2Q-DEC`（半年，6月/12月）
- 考慮交易成本（bps）
- 持有期間自然漂移（Drift）模擬，不強制每月重置
- 同步計算等權重（Equal Weight）與 60/40 基準組合進行對比

### 互動式儀表板（Streamlit）
- 4 種投資人風險偏好一鍵切換（積極、成長、穩健、保守）
- 側邊欄即時調整回測參數（頻率、目標函數、上限約束、Lookback 期間）
- 績效總覽表、NAV 曲線比較、歷史權重分析

---

## 環境安裝

**系統需求：** Python 3.10 以上

```bash
# 建立虛擬環境（建議）
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 安裝相依套件
pip install -r requirements.txt
```

**套件版本需求：**

| 套件 | 版本 |
|---|---|
| pandas | ≥ 2.0 |
| numpy | ≥ 1.24 |
| PyPortfolioOpt | ≥ 1.5 |
| cvxpy | ≥ 1.4 |
| streamlit | ≥ 1.33 |
| scikit-learn | ≥ 1.3 |
| statsmodels | ≥ 0.14 |

---

## 快速開始

### 方式一：Streamlit Web UI（推薦）

```bash
streamlit run ui/app.py
```

開啟後預設網址為 `http://localhost:8501`。

**操作流程：**
1. 側邊欄選擇「投資人類型」
2. 依需求調整進階參數（頻率、目標函數、資產上限等）
3. 點擊「▶️ Run Backtest」執行
4. 查看三個分頁：績效總覽、策略對比圖、權重分析

### 方式二：CLI 執行完整 Pipeline

```bash
python main.py
```

執行後，結果自動輸出至 `outputs/` 資料夾。預設採用 `config.yaml` 的設定（`Q` 再平衡、`sortino` 目標函數）。

---

## 設定檔說明 (`config.yaml`)

```yaml
project:
  timezone: Asia/Taipei
  price_return_method: simple   # 報酬率計算方式：simple（算術）| log（對數）

paths:
  data_dir: data
  expected_return_xlsx: "指數預期報酬率-1.xlsx"   # 股票/債券基本面資料
  module_return_xlsx: "模組報酬率.xlsx"            # 歷史價格/報酬率資料

universe:
  market_list:    # 股票市場清單（Bloomberg Ticker）
    - "SPX Index"    # 美股 S&P 500
    - "SXXP Index"   # 歐股 STOXX 600
    - "NKY Index"    # 日股 Nikkei 225
    - "MXMS Index"   # 新興市場
    - "SHCOMP Index" # 中國 A 股
    - "TWSE Index"   # 台股
  industry_list:
    - "科技"
  bond_list:
    - "投資級債"
    - "非投資級債"
    - "新興市場債"
  benchmark_cols:   # 60/40 基準組合欄位（Bloomberg Ticker）
    - "LUCRTRUU_Index"   # 美國投資級債指數
    - "LEGATRUU_Index"   # 全球總債券指數
    - "LG30TRUU_Index"   # 美國長期公債指數

dates:
  start_date: "2010-12-31"       # 資料起始點（開始建構第一期模型）
  backtest_start: "2012-01-31"   # 回測績效統計起始
  backtest_end: "2025-10-31"     # 回測結束日

schedule:
  T_months: 180                  # 總滾動期間長度（月數）
  weight_update_freq_months: 1   # 每幾個月更新一次預期報酬
  rebalance_rule: "Q"            # 預設再平衡頻率（CLI 用）

risk:
  lookback_months: 36            # 共變異數估計回顧窗口（月數）
  mar: 0.0                       # Sortino 下行門檻（月報酬率，0.0 = 0%）
  cov_method: ledoitwolf         # 共變異數方法：ledoitwolf | sample
  annualize_factor: 12           # 年化因子（月頻資料 = 12）

return_model:
  rolling_years: 5               # EPS 成長率計算滾動年數
  lookback_mom_months: 3         # 動能計算回顧月數

constraints:
  lower: 0.0                     # 單一資產配置下限（0 = 不強制做空）
  upper: 0.5                     # 單一資產配置上限
  stock_type_limit: 0.7          # 股票（市場 + 產業）總權重上限

optimizer:
  objective: "sortino"           # 目標函數：sharpe | sortino | utility | min_variance
  l2_gamma: 0.1                  # L2 正則化強度（防止極端集中）
  risk_aversion: 2.0             # 效用函數風險趨避係數（utility 模式用）

backtest:
  starting_capital: 1.0          # 初始資本（倍數，1.0 = 100%）
  trading_cost_bps: 0.0          # 交易成本（基點，0.0 = 不考慮）
  rf_annual: 0.0                 # 年化無風險利率
```

### 投資人類型對應的預設設定

| 投資人類型 | 目標函數 | 股票上限 | 單一資產上限 | 特殊限制 |
|---|---|---|---|---|
| 積極型 | Sortino | 70%（config 值） | 50%（config 值） | 無 |
| 成長型 | Sharpe | 60% | 20% | 無 |
| 穩健型 | Utility | 40% | 20% | 排除產業類別 |
| 保守型 | Min Variance | 0% | 100% | 僅投資級債 + 非投資級債；非投資級債 ≤ 20% |

---

## 模型方法論

### 1. 預期報酬模型（`engine/return_model.py`）

#### 股票市場
```
E[R] = EPS成長率 + 股息殖利率 + PE均值回歸調整
```
- **EPS 成長率**：5 年滾動複合年化成長率（CAGR）
- **股息殖利率**：12 個月平均殖利率
- **PE 均值回歸**：`(PE_mean / PE_current)^(1/rolling_years) - 1`，反映估值向長期均值回歸的預期資本利得

#### 固定收益
```
E[R] ≈ YTM - Duration × (Forecast_Yield - Current_Yield)
```
- 利率上升 → 債券預期報酬下降（資本損失）
- 利率下降 → 債券預期報酬上升（資本利得）

#### 產業（CAPM）
```
E[R] = Rf + β × (E[R_market] - Rf)
```
- Beta 相對 S&P 500 動態估計（滾動回歸）

---

### 2. 風險模型（`engine/risk_model.py`）

**Ledoit-Wolf Shrinkage**（預設）：
```
Σ_shrunk = (1 - α) × Σ_sample + α × Σ_target
```
- 收縮至對角矩陣目標，降低估計誤差
- 適用於樣本數相對資產數不夠大時（本系統 lookback 36 月、10+ 資產）
- 比純樣本共變異數更穩健，避免極端權重配置

---

### 3. 最佳化（`engine/optimizer.py`）

求解最佳化問題：
```
max  f(w)
s.t. 0 ≤ w_i ≤ upper_i            （個別資產上下限）
     Σ w_i = 1                     （全額投資）
     Σ w_i (i∈Stocks) ≤ stock_limit （股票類總上限）
```

使用 L2 正則化（`l2_gamma`）防止過度集中：
```
f_regularized(w) = f(w) - γ × ||w||²
```

---

### 4. 回測引擎（`engine/backtest.py`）

**時間對齊邏輯（避免前視偏差 Look-ahead Bias）：**
```
t-1 月末資料 → 建立 μ 和 Σ → 求解 w(t) → 用 t 月的實際報酬 r(t) 計算績效
```

**持有期間 Drift 模擬：**
- 再平衡日之間，持倉依市場價格自然漂移
- 再平衡日執行調倉，計算交易成本（`|target_hold - current_hold| × cost_rate`）

**績效指標定義：**
| 指標 | 公式 |
|---|---|
| CAGR | `(NAV_end / NAV_start)^(1/years) - 1` |
| Sharpe | `mean(r_excess) × 12 / (std(r) × √12)` |
| Sortino | `mean(r_excess) × 12 / (downside_std × √12)` |
| MDD | `min(NAV / cummax(NAV) - 1)` |
| Calmar | `CAGR / |MDD|` |

---

## 輸出檔案說明

執行 `python main.py` 後，`outputs/` 資料夾產生以下檔案：

| 檔案 | 內容 | 格式 |
|---|---|---|
| `weights.csv` | 每月末模型建議配置權重（各資產 %) | `index=date, columns=asset` |
| `returns.csv` | 各資產月報酬率序列 | `index=date, columns=asset` |
| `nav_Q.csv` | 季再平衡策略 NAV 曲線 | `index=date, value=nav` |
| `nav_M.csv` | 月再平衡策略 NAV 曲線 | 同上 |
| `nav_A.csv` | 年再平衡策略 NAV 曲線 | 同上 |
| `nav_2Q-DEC.csv` | 半年（6/12月）再平衡 NAV 曲線 | 同上 |
| `stats.json` | 各再平衡頻率下完整績效指標 | JSON |
| `summary.csv` | 所有再平衡頻率績效摘要比較表 | `index=rebalance_rule` |

---

## 資料來源

本系統從 `data/` 資料夾讀取兩個 Excel 檔案：

### `指數預期報酬率-1.xlsx`
包含以下 Sheet（各市場/債券/產業分頁）：
- 各股票指數的 Price、EPS、Dividend Yield、PE 等基本面數據
- 各債券的 YTM、Duration、利率預測
- 各產業的價格序列

### `模組報酬率.xlsx`
包含：
- 各資產歷史月報酬率或價格指數
- Benchmark 指數（60/40 基準用）

> **注意：** Excel 檔案欄位名稱需與 `data_loader.py` 中的讀取邏輯一致。更新資料時，請確認欄位對應無誤。

---

## 常見問題

**Q: 執行後出現 `KeyError` 或 `NaN` 在 weights？**
- 確認 `data/` 資料夾內的兩個 Excel 檔案存在且欄位完整
- 執行 `python debug_data_quality.py` 診斷資料品質

**Q: `streamlit run ui/app.py` 後按 Run 沒反應或出錯？**
- 確認已在專案根目錄執行，而非 `ui/` 子目錄
- 確認 `config.yaml` 路徑設定正確（側邊欄的 `config.yaml 路徑` 欄位）

**Q: Optimizer 報 `Optimization failed`？**
- 可能是預期報酬向量 `μ` 全為負，導致無可行解
- 嘗試調整 `lookback_months`（如從 36 改為 24）
- 嘗試切換 `objective` 為 `min_variance`（對 μ 品質最不敏感）
- 檢查 `constraints.upper` 是否設得太低，導致約束過緊

**Q: Numpy / Pandas 版本不相容？**
- 確認 numpy ≥ 1.24，pandas ≥ 2.0
- pandas 2.0 起 `resample("M")` 已改為 `resample("ME")`，本系統已更新相容
