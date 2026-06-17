# 量化模型投組研究平台 (Quantitative Model Portfolio Research Platform)

> 整合 SAA（戰略資產配置）Markowitz 最佳化與 TAA（戰術資產配置）三層訊號的內部量化研究工具。
> 提供前瞻性預期報酬建模、滾動回測，以及 Streamlit 互動儀表板與 HTML 策略報告生成。

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
├── report_builder.py        # HTML 報告建構（整合月報文字 AI 摘要）
├── preview_report.py        # 報告快速預覽 / 摘要微調 CLI
├── install.bat              # Windows 首次安裝（雙擊，建 venv + 裝套件）
├── start.bat                # Windows 一鍵啟動（雙擊）
│
├── engine/                  # 核心量化引擎（純計算，無 UI 依賴）
│   ├── config.py            # YAML 設定讀取
│   ├── data_loader.py       # 資料讀取與前處理
│   ├── return_model.py      # 前瞻性預期報酬模型（SAA）
│   ├── risk_model.py        # 共變異數矩陣估計（Ledoit-Wolf）
│   ├── optimizer.py         # 投組最佳化求解器（PyPortfolioOpt）
│   ├── backtest.py          # 滾動回測與績效計算
│   ├── constraints.py       # 最佳化限制條件輔助
│   ├── taa.py               # TAA 訊號引擎（三層模型）
│   └── utils.py             # 報酬率計算工具
│
├── ui/
│   └── app.py               # Streamlit Web 儀表板（SAA + TAA）
│
├── data/                    # 原始資料（不納入版控）
│   ├── SAA_RawData.xlsx         # SAA 基本面資料（股票/債券/Benchmark）
│   ├── TAA_RawData.xlsx         # TAA 總體指標（PMI/NFP/Fed/SPX/ERP）
│   ├── taa_history_*.csv        # TAA 指標歷史補充（可選，fetch_taa_history.py 產生）
│   └── fetch_taa_history.py     # TAA 歷史資料抓取腳本
│
├── report/                  # HTML 報告產出目錄（_preview*.html，不納入版控）
│
└── outputs/                 # 回測產出（不納入版控）
    ├── weights.csv          # SAA 月頻建議配置權重
    ├── returns.csv          # 各資產月報酬率序列
    ├── nav_Q.csv            # 季再平衡 NAV 曲線
    ├── summary.csv          # 各頻率績效摘要
    ├── weights_taa.csv      # SAA+TAA 月頻調整後權重
    ├── taa_signals.csv      # TAA 每月訊號明細
    └── nav_taa_Q.csv        # SAA+TAA 季再平衡 NAV 曲線
```

---

## 功能特色

### SAA：前瞻性預期報酬模型
- **股票市場**：EPS 5 年滾動成長率 + 12 月平均殖利率 + PE 均值回歸調整
- **固定收益**：基於 YTM 與 Duration 的利率敏感度估計
- **產業**：CAPM Beta 動態估計（相對 S&P 500）

### SAA：多目標投組最佳化

| 目標函數 | 說明 | 適用投資人 |
|---|---|---|
| `sortino` | 最大化 Sortino Ratio（下行風險調整） | 積極型 |
| `sharpe` | 最大化 Sharpe Ratio（全波動風險調整） | 成長型 |
| `utility` | 最大化二次效用函數（含風險趨避係數） | 穩健型 |
| `min_variance` | 最小化投組波動度 | 保守型 |

### SAA：動態回測引擎
- 4 種再平衡頻率：`M`（月）、`Q`（季）、`A`（年）、`2Q-DEC`（半年，6月/12月）
- 考慮交易成本（bps）
- 持有期間自然漂移（Drift）模擬，不強制每月重置
- 同步計算等權重（Equal Weight）與 60/40 基準組合進行對比

### TAA：戰術調整覆蓋層
在 SAA 最佳化權重之上疊加動態股債比調整，由三層訊號決定方向與幅度：

1. **總體面**（macro）：PMI + 非農就業（NFP）+ Fed 升降息循環各給 +1/0/-1，加總決定方向
2. **市場面**（market）：SPX 月底收盤 vs 200 日均線——訊號一致時直接執行；方向相反時觸發「會議討論旗標」，提示人工覆核
3. **評價面**（valuation）：ERP 相對 ±1σ 決定調整幅度乘數（1.0 / 0.75 / 0.5）

調整公式：`ΔX = direction × X × multiplier`

| 投資人類型 | 最大調整幅度 X |
|---|---|
| 積極型 | 10% |
| 成長型 | 8% |
| 穩健型 | 6% |
| 保守型 | 0%（TAA 不啟用） |

### 互動式儀表板（Streamlit）
- 4 種投資人風險偏好一鍵切換（積極、成長、穩健、保守）
- 側邊欄即時調整回測參數（頻率、目標函數、上限約束、Lookback 期間）
- TAA 面板：ΔX 滑桿、PMI/NFP 門檻、ERP 乘數、最終期人工覆核功能
- 績效總覽表、NAV 曲線比較（含 SAA+TAA 對比）、歷史權重分析

---

## 環境安裝

**系統需求：** Python 3.10 或 3.11（開發環境為 3.10.9）。`requirements.txt` 已鎖定精確版本，確保各機器環境一致。

### Windows（最簡單）

直接**雙擊 `install.bat`**：自動建立 `venv`、安裝套件，並檢查 `.env` 與 `data/` 是否就緒。完成後日後啟動只要雙擊 `start.bat`。

### macOS / Linux（或想手動安裝）

```bash
python -m venv venv
source venv/bin/activate          # macOS / Linux
# venv\Scripts\activate           # Windows（手動）

pip install -r requirements.txt
```

> ⚠️ `venv/` **不能跨作業系統或跨電腦複製**（內含平台相依的執行檔），換機器一定要重建。

**主要套件**（完整鎖定清單見 `requirements.txt`）：

| 套件 | 用途 |
|---|---|
| pandas / numpy | 資料處理與數值計算 |
| PyPortfolioOpt / cvxpy | 投組最佳化與求解器 |
| scikit-learn / statsmodels | 統計模型與分析 |
| streamlit / plotly | Web UI 與互動圖表 |
| openpyxl | 讀取 Excel 資料 |
| anthropic / google-generativeai | AI 摘要（Claude / Gemini，選用） |
| python-dotenv | 讀取 `.env` API 金鑰 |

---

## 快速開始

### 啟動方式一：雙擊（Windows，給非工程使用者）

雙擊 `start.bat` → 黑色視窗別關 → 瀏覽器自動開啟 `http://localhost:8501`。詳見 `OPERATIONS.md` 第 0 章。

### 啟動方式二：在 terminal 下指令（Mac / 進階）

先啟用虛擬環境，再啟動 Streamlit。**務必在專案根目錄執行**（不能進 `ui/` 子目錄）。

```bash
# macOS / Linux
cd /path/to/model_portfolio
source venv/bin/activate
streamlit run ui/app.py
```
```bat
REM Windows（命令提示字元，等同雙擊 start.bat）
cd C:\KGI\model_portfolio
venv\Scripts\activate
streamlit run ui/app.py
```

開啟後預設網址為 `http://localhost:8501`。

**UI 操作流程：**
1. （每月）在左側「資料來源」上傳最新的 `SAA_RawData.xlsx` / `TAA_RawData.xlsx`
2. 側邊欄選擇「投資人類型」
3. 依需求調整進階參數（頻率、目標函數、資產上限等）
4. 展開「TAA 設定」面板，確認 ΔX 幅度與訊號門檻
5. 點擊「▶️ Run Backtest」執行
6. 查看績效總覽、策略對比圖、權重分析，再按「生成報告」產出 HTML 策略報告

**AI 摘要模型選擇（`--ai-provider`）：**

| 指令 | 說明 | 需要 |
|---|---|---|
| `streamlit run ui/app.py` | **Gemini 2.5 Flash（預設）** | `GEMINI_API_KEY` |
| `streamlit run ui/app.py -- --ai-provider sonnet` | Claude Sonnet 4.6 | `ANTHROPIC_API_KEY` |
| `streamlit run ui/app.py -- --ai-provider opus` | Claude Opus 4.8 | `ANTHROPIC_API_KEY` |
| `streamlit run ui/app.py -- --ai-provider nlg` | 規則式摘要（不需 API） | 無 |

設定 API 金鑰（寫入專案根目錄的 `.env`，**不會進版控**）：
```bash
GEMINI_API_KEY="your_key_here"
ANTHROPIC_API_KEY="your_key_here"
```

> 未安裝對應套件、找不到 API key、或 API 呼叫失敗時，會自動降回規則式摘要，並在終端機印出原因、報告來源標籤標示「自動退回」。

---

## 報告產生與 AI 摘要微調（terminal）

報告的「AI 策略摘要」會整合 **`TAA_RawData.xlsx` 的「月報文字」分頁**觀點與本期模型結論，產出一段研究報告風格的市場分析（含匯率／股市／債市看法）。除了用 UI 的「生成報告」按鈕，也可在 terminal 用 `preview_report.py` 快速預覽與微調——**這些微調只走 CLI，不會出現在 UI 介面**。

```bash
source venv/bin/activate        # Windows 改 venv\Scripts\activate

# 1) 直接預覽（讀 .last_run.pkl，不需重跑回測）
python preview_report.py                 # 預設季再平衡(Q) + Gemini 摘要
python preview_report.py M               # 指定再平衡頻率 M/Q/A/2Q-DEC

# 2) 微調摘要：用自然語言「下指令」，重生一次（最常用）
python preview_report.py --tweak "日圓那段講保守一點，並強調非投等債的息收優勢"

# 3) 整段定稿覆寫：自己寫好全文，直接取代、跳過 LLM（要逐字掌控時）
python preview_report.py --override-file my_summary.txt

# 4) 指定模型
python preview_report.py --ai-provider sonnet --tweak "提到新任 Fed 主席沃許"
```

執行後會輸出 `report/_preview.html`，並在 `http://localhost:8765` 起一個本機預覽（Ctrl+C 結束）。

| 參數 | 作用 |
|---|---|
| `--tweak "<指令>"` | 附加到摘要 prompt 的微調指令（最高優先）。**不會被記住**，只作用於這一次 |
| `--override-file <路徑>` | 用檔案內的全文直接當摘要，跳過 LLM；來源標示「人工修訂定稿」 |
| `--ai-provider <模型>` | `gemini`（預設）/ `sonnet` / `opus` / `nlg` |

> 等價的環境變數：`SUMMARY_TWEAK` / `SUMMARY_OVERRIDE_FILE`（連 UI 產出也會套用，但畫面上看不到任何微調欄位）。
>
> ⚠️ `--tweak` 需要 LLM（Gemini/Claude）才生效；若在沒裝套件的 Python 環境（如 anaconda base）執行，會退回規則式且忽略微調——請確認在專案 `venv` 內執行（提示字開頭應為 `(venv)`）。

---

## CLI 執行完整 Pipeline

```bash
python main.py
```

執行後，SAA 結果輸出至 `outputs/`；若 `taa.enabled: true`，同時輸出 TAA 比較結果（`weights_taa.csv`、`taa_signals.csv`、`nav_taa_Q.csv`）。`main.py` 會完整載入所有資料，可用來驗證每月更新的 Excel 是否有缺漏。

---

## 設定檔說明 (`config.yaml`)

```yaml
project:
  timezone: Asia/Taipei
  price_return_method: simple   # simple（算術）| log（對數）

paths:
  data_dir: data
  saa_raw_xlsx: "SAA_RawData.xlsx"     # SAA 基本面資料
  taa_raw_xlsx: "TAA_RawData.xlsx"     # TAA 總體指標資料

universe:
  market_list:
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
  benchmark_cols:
    - "MXWO_Index"        # 全球股票指數
    - "LEGATRUU_Index"    # 全球總債券指數
    - "LG30TRUU_Index"    # 美國長期公債指數

dates:
  start_date: "2010-12-31"
  backtest_start: "2012-01-31"
  backtest_end: "auto"           # auto = 自動偵測 RETURN 工作表最新月份；亦可鎖定具體日期如 "2025-10-31"

schedule:
  rebalance_rule: "Q"            # M | A | Q | 2Q-DEC（CLI 預設）

risk:
  lookback_months: 36            # 共變異數估計回顧窗口（月數）
  mar: 0.0                       # Sortino 下行門檻（月報酬率）
  cov_method: ledoitwolf         # ledoitwolf | sample
  annualize_factor: 12

return_model:
  rolling_years: 5               # EPS 成長率計算滾動年數
  lookback_mom_months: 3         # 動能計算回顧月數

constraints:
  lower: 0.0
  upper: 0.5                     # 單一資產配置上限（積極型預設）
  stock_type_limit: 0.7          # 股票（市場+產業）總權重上限
  bond_type_floor: 0.2           # 債券總權重下限（積極型預設）

optimizer:
  objective: "sortino"           # sharpe | sortino | utility | min_variance
  l2_gamma: 0.1                  # L2 正則化強度
  risk_aversion: 2.0             # 效用函數風險趨避係數（utility 模式用）

backtest:
  starting_capital: 1.0
  trading_cost_bps: 0.0          # 交易成本（基點）
  rf_annual: 0.0                 # 年化無風險利率

taa:
  enabled: true
  profile_max_adjust:            # 各投資人類型最大調整幅度 X
    積極型投資人: 0.10
    成長型投資人: 0.08
    穩健型投資人: 0.06
    保守型投資人: 0.00           # 0 = TAA 不啟用
  nfp_threshold: 50              # 非農就業門檻（千人）
  pmi_threshold: 50              # PMI 榮枯線
  valuation_multipliers:
    plus_1: 1.00                 # ERP > +1σ（便宜）→ 全額 X
    zero:   0.75                 # ERP ±1σ 之間（正常）→ 75% X
    minus_1: 0.50                # ERP < -1σ（昂貴）→ 50% X
  add_target: "SPX_Index"        # 加碼時股票倉位流入的資產
  reduce_target: "投資級債"       # 減碼時債券倉位流入的資產
```

### 投資人類型對應的預設設定

| 投資人類型 | 目標函數 | 股票上限 | 債券下限 | 單一資產上限 | 特殊限制 | TAA X |
|---|---|---|---|---|---|---|
| 積極型 | Sortino | 70% | 20% | 50% | — | 10% |
| 成長型 | Sharpe | 60% | 40% | 20% | — | 8% |
| 穩健型 | Utility | 40% | 60% | 20% | 排除產業類別 | 6% |
| 保守型 | Min Variance | 0% | 100% | 100% | 僅投資級債 + 非投資級債；非投資級債 ≤ 20% | 不啟用 |

---

## 模型方法論

### 1. 預期報酬模型（`engine/return_model.py`）

**股票市場：**
```
E[R] = EPS成長率 + 股息殖利率 + PE均值回歸調整
```
- **EPS 成長率**：5 年滾動複合年化成長率（CAGR）
- **股息殖利率**：12 個月平均殖利率
- **PE 均值回歸**：`(PE_mean / PE_current)^(1/rolling_years) - 1`，反映估值向長期均值回歸的預期資本利得

**固定收益：**
```
E[R] ≈ YTM - Duration × (Forecast_Yield - Current_Yield)
```
利率上升 → 債券預期報酬下降；利率下降 → 上升。

**產業（CAPM）：**
```
E[R] = Rf + β × (E[R_market] - Rf)
```
Beta 相對 S&P 500 動態估計（滾動迴歸）。

---

### 2. 風險模型（`engine/risk_model.py`）

**Ledoit-Wolf Shrinkage**（預設）：
```
Σ_shrunk = (1 - α) × Σ_sample + α × Σ_target
```
收縮至對角矩陣目標，適用於樣本期相對資產數不夠大的情況（lookback 36 月、10+ 資產）。比純樣本共變異數更穩健，避免極端權重配置。

---

### 3. 最佳化（`engine/optimizer.py`）

```
max  f(w)
s.t. 0 ≤ w_i ≤ upper_i
     Σ w_i = 1
     Σ w_i (i∈Stocks) ≤ stock_limit
     Σ w_i (i∈Bonds)  ≥ bond_floor
```

L2 正則化防止過度集中：`f_reg(w) = f(w) - γ × ||w||²`

**後處理（min weight floor）：**
1. 剔除小於 1% 的零頭部位（設為 0）
2. 重新正規化使權重和等於 1
3. 迭代修正上限違反（個別上限 + 股票組別上限），超出部分等比重分配至其他資產

---

### 4. 回測引擎（`engine/backtest.py`）

**時間對齊（避免前視偏差 Look-ahead Bias）：**
```
t-1 月末資料 → 建構 μ 和 Σ → 求解 w(t) → 用 t 月實際報酬 r(t) 計算績效
```

**績效指標：**
| 指標 | 公式 |
|---|---|
| CAGR | `(NAV_end / NAV_start)^(1/years) - 1` |
| Sharpe | `mean(r_excess) × √12 / std(r)` |
| Sortino | `mean(r_excess) × √12 / downside_std` |
| MDD | `min(NAV / cummax(NAV) - 1)` |
| Calmar | `CAGR / |MDD|` |

---

### 5. TAA 訊號引擎（`engine/taa.py`）

**第一層：總體面（macro）**

| 指標 | +1（偏多） | -1（偏空） | 0（中性） |
|---|---|---|---|
| PMI | PMI > 50 且 3MA > 6MA | PMI < 50 且 3MA < 6MA | 其他 |
| NFP | NFP > 50K 且 3MA > 6MA | NFP < 50K 且 3MA < 6MA | 其他 |
| Fed | 降息循環中（diff < 0） | 升息循環中（diff > 0） | 停止升降息連 2 期 |

`macro_score = PMI_score + NFP_score + Fed_score`，`direction = sign(macro_score)`

**第二層：市場面（market）**

- `direction > 0` 且 `SPX < 200MA`：觸發 `meeting_flag`（趨勢未確認，提示人工覆核）
- `direction < 0` 且 `SPX > 200MA`：同上

**第三層：評價面（valuation）**

| ERP 位置 | 加碼方向乘數 | 減碼方向乘數 |
|---|---|---|
| ERP > +1σ（便宜） | 1.00 | 0.50 |
| ±1σ 之間（正常） | 0.75 | 0.75 |
| ERP < -1σ（昂貴） | 0.50 | 1.00 |

**最終調整：**
```
ΔX = direction × X × multiplier
```
- 加碼（ΔX > 0）：從債券各部位等比減倉 ΔX，全數移入 `add_target`（SPX）
- 減碼（ΔX < 0）：從股票各部位等比減倉 |ΔX|，全數移入 `reduce_target`（投資級債）
- **時間對齊**：持有月 D 使用「D 前一月末」可觀測訊號，與 SAA 決策邏輯一致

---

## 輸出檔案說明

執行 `python main.py` 後，`outputs/` 資料夾產生以下檔案：

| 檔案 | 內容 | 格式 |
|---|---|---|
| `weights.csv` | SAA 每月末建議配置權重 | `index=date, columns=asset` |
| `returns.csv` | 各資產月報酬率序列 | `index=date, columns=asset` |
| `nav_Q.csv` | SAA 季再平衡 NAV 曲線 | `index=date` |
| `summary.csv` | 各再平衡頻率績效摘要 | `index=rebalance_rule` |
| `weights_taa.csv` | SAA+TAA 調整後月頻權重 | `index=date, columns=asset` |
| `taa_signals.csv` | TAA 每月訊號明細（方向/乘數/ΔX/meeting_flag） | `index=date` |
| `nav_taa_Q.csv` | SAA+TAA 季再平衡 NAV 曲線 | `index=date` |

---

## 資料來源

### `SAA_RawData.xlsx`（SAA 基本面資料）

| 工作表 | 必要欄位 | 說明 |
|---|---|---|
| 各股票指數（如 SPX INDEX） | `Price`、`近12個月每股盈餘`、`股利率12個月殖利率-毛額`、`BEst本益比` | 兩行表頭（row 1 代碼, row 2 名稱），月頻 |
| RETURN | 各資產月報酬率或收盤價序列 + 債券 YTM/Duration 欄位 | 月頻 |
| MXWO_LEGATRUU_LG30TRUU INDEX | Benchmark 月底收盤 | 月頻 |

### `TAA_RawData.xlsx`（TAA 總體指標資料）

| 工作表 | 必要欄位 | 說明 |
|---|---|---|
| 總體面因子 | `NAPMALL Index`（PMI）、`NFP TCH Index`（非農就業）、`FDTR Index`（聯邦基金利率） | 月頻 |
| 市場面因子 | SPX 最新價（col 1）、200 日均線（col 2） | 日頻，系統自動取月底 |
| 評價面因子 | `價差`（ERP）、`AVG+1XSIGMA`、`AVG-1XSIGMA` | 日頻，系統自動取月底 |
| 月報文字（選用） | 兩欄：主題／內文（美國經濟、美國股市、殖利率/Fed、債券看法、匯率…） | 報告 AI 摘要的素材；留空不影響回測 |

**TAA 歷史補充（可選）：**

若 `data/` 目錄下存在 `taa_history_fdtr.csv`、`taa_history_nfp.csv`、`taa_history_pmi.csv`，系統自動補充 Excel 缺少的早期歷史（Excel 資料優先，CSV 僅填補 NaN）。可執行 `data/fetch_taa_history.py` 從 FRED 等公開來源抓取。

> 工作表名稱與欄位名稱需與 `engine/data_loader.py` 定義一致，變動時需同步修改。

---

## 常見問題

**Q: `KeyError: 'XXX Index'` 或 `Sheet not found`？**
- 確認 `config.yaml` 的 `universe.*_list` 資產名稱與 Excel 工作表名稱完全一致（含空格、大小寫）
- 執行診斷：
  ```python
  import pandas as pd
  xl = pd.ExcelFile("data/SAA_RawData.xlsx")
  print(xl.sheet_names)
  ```

**Q: 按 Run Backtest 後沒反應或 `Optimization failed`？**
- 確認從專案根目錄執行 `streamlit run ui/app.py`，不能在 `ui/` 子目錄下執行
- 可能是預期報酬 μ 全為負，嘗試切換 `objective` 為 `min_variance` 或降低 `lookback_months`
- 確認 `constraints.upper` 設定合理（個別上限過低易導致無可行解）

**Q: TAA 訊號與預期不符？**
- 確認 `TAA_RawData.xlsx` 三張工作表均已更新到最新月份
- UI 側邊欄的「本期參考訊號」會顯示當期 direction / multiplier / meeting_flag；`meeting_flag = True` 表示總體面與市場面方向相反，需人工判斷是否覆核

**Q: `ModuleNotFoundError: No module named 'engine'`？**
- 需從專案根目錄執行；不能在 `ui/` 或 `engine/` 子目錄直接執行 Python

**Q: `Streamlit` 修改 config 後顯示舊結果？**
- 點擊瀏覽器上方「⟳」清除快取，或在終端機 `Ctrl+C` 重啟 Streamlit

**Q: Numpy / Pandas 版本不相容？**
- 確認 numpy ≥ 1.24、pandas ≥ 2.0
- pandas 2.0 起已將 `resample("M")` 改為 `resample("ME")`，本系統已相容
