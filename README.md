# 📊 Quantitative Model Portfolio Research Platform (量化投組研究平台)

## 專案簡介

這是一個專業的量化投資組合管理與回測系統，旨在協助研究員建構、回測並分析多重資產類別的投資組合。系統採用**前瞻性的預期報酬模型 (Forward-Looking Expected Returns)** 與**穩健的風險模型 (Robust Risk Models)**，並透過 Streamlit 提供互動式的分析介面，讓使用者能快速驗證不同的資產配置策略。

---

## 🔥 核心功能

*   **動態回測 (Dynamic Backtesting)**
    *   支援月 (Monthly)、季 (Quarterly)、年 (Annually) 等不同頻率的滾動再平衡。
    *   考慮實際交易成本 (Trading Costs) 與價格滑價。
*   **先進最佳化 (Advanced Optimization)**
    *   基於 `PyPortfolioOpt` 實作。
    *   支援 **Mean-Variance (Sharpe)**, **Mean-Semivariance (Sortino)**, **Utility Maximization** 等目標函數。
    *   可設定單一資產、資產類別 (Stocks/Bonds) 的權重上下限約束。
*   **自定義因子模型 (Custom Factor Models)**
    *   **股票**: 結合成長性 (Growth)、股息 (Yield) 與估值回歸 (Valuation Mean Reversion) 的前瞻預測。
    *   **債券**: 結合殖利率 (YTM)、存續期間 (Duration) 與利率預測模型。
    *   **產業**: 基於 CAPM 模型動態估計 Beta。
*   **互動儀表板 (Interactive Dashboard)**
    *   透過 Web UI (Streamlit) 即時調整參數。
    *   可視化 NAV 績效曲線、Drawdown、資產配置權重變化。

---

## 🚀 快速開始

### 1. 環境設定

本專案使用 Python 3.10+。建議建立虛擬環境以保持依賴套件純淨。

```bash
# 建立虛擬環境 (Mac/Linux)
python -m venv .venv
source .venv/bin/activate

# 建立虛擬環境 (Windows)
# python -m venv .venv
# .venv\Scripts\activate

# 安裝相依套件
pip install -r requirements.txt
```

> **注意**: 若遇到 Numpy 版本問題，請確保 numpy 版本小於 2.0 (`pip install "numpy<2"`).

### 2. 啟動 Web UI (推薦)

這是最直觀的使用方式。

```bash
streamlit run ui/app.py
```

啟動後，請在瀏覽器打開終端機顯示的網址 (通常是 `http://localhost:8501`)。
您可以在側邊欄調整：
*   再平衡頻率 (M/Q/A)
*   最佳化目標 (Sortino/Sharpe/Utility)
*   風險回顧期間 (Lookback Window)
*   資產配置上限約束

### 3. 執行完整 Pipeline (CLI)

若需要批量產出數據或進行除錯，可直接執行主程式：

```bash
python main.py
```

執行完畢後，所有結果將輸出至 `outputs/` 資料夾。

---

## 🏗️ 專案結構

```text
model_portfolio/
├── config.yaml          # ⚙️ 全局參數設定 (回測區間、資產限制、模型參數)
├── requirements.txt     # 📦 Python 套件清單
├── main.py             # 🚀 主程式入口 (CLI / Pipeline Orchestrator)
├── ui/                 # 🖥️ Web Interface
│   └── app.py          # Streamlit App 入口
├── engine/             # 🧠 核心計量引擎
│   ├── data_loader.py  # 資料讀取與前處理 (Resampling / Cleaning)
│   ├── return_model.py # 預期報酬模型 (Fundamental / CAPM Logic)
│   ├── risk_model.py   # 風險模型 (Ledoit-Wolf Shrinkage)
│   ├── optimizer.py    # 投組最佳化求解器
│   ├── backtest.py     # 滾動回測邏輯 (Rolling Window Simulation)
│   └── constraints.py  # 最佳化限制條件輔助函式
├── outputs/            # 📤 產出報告與數據 (Weights, Returns, NAV, Stats)
└── report/             # 📊 績效指標計算 (Sharpe, MDD, CAGR)
```

---

## 📐 模型方法論

### 1. 預期報酬模型 (Return Model)
不同於傳統使用歷史平均報酬，本模型採用 **Component-based** 的前瞻性估計：

*   **股票 (Equities)**
    $$ E[R] = \text{Dividend Yield} + \text{EPS Growth} + \Delta \text{Valuation (PE)} $$
    *   *EPS Growth*: 採用 5 年滾動複合成長率。
    *   *Valuation*: 假設 PE 會向長期平均回歸 (Mean Reversion)。

*   **債券 (Fixed Income)**
    $$ E[R] \approx \text{YTM} - \text{Duration} \times (\text{Forecast Yield} - \text{Current Yield}) $$
    *   反映持有收益與利率變動造成的資本利得/損失。

### 2. 風險模型 (Risk Model)
*   **Ledoit-Wolf Shrinkage**: 用於估計資產共變異數矩陣 ($\Sigma$)。
*   此方法能有效解決小樣本估計誤差，避免極端權重配置，比單純的樣本共變異數 (Sample Covariance) 更穩定。

### 3. 最佳化 (Optimization)
使用 `PyPortfolioOpt` 求解以下目標函數：

*   **Maximum Sortino Ratio**:
    最大化 $\frac{R_p - R_f}{\sigma_{downside}}$。比 Sharpe Ratio 更適合追求絕對報酬的投資人，因為它只懲罰下行波動。
*   **Maximum Sharpe Ratio**:
    最大化 $\frac{R_p - R_f}{\sigma_p}$。傳統 MPT 的標準解。

---

## 📤 輸出檔案說明 (`outputs/`)

| 檔案名稱 | 說明 |
| :--- | :--- |
| `weights.csv` | 每一期再平衡時，各資產的配置權重 |
| `returns.csv` | 各個資產的月報酬率序列 |
| `nav_*.csv` | 策略的淨值曲線 (Net Asset Value) |
| `stats.json` | 最終績效統計 (CAGR, MDD, Sharpe, Sortino) |
| `summary.csv` | 綜合摘要報表 |
