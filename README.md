```markdown

```

```

---

# 🏗️ 專案結構

```

model_portfolio/
├── main.py # 🚀 主程式入口（跑完整 pipeline）
├── config.yaml # ⚙️ 所有策略參數設定
├── requirements.txt # 📦 套件需求
├── data/ # 📂 原始資料（Excel）
│ ├── 指數預期報酬率-1.xlsx
│ └── 模組報酬率.xlsx
├── outputs/ # 📤 所有輸出結果
│ ├── weights.csv # 每期最適權重
│ ├── returns.csv # 資產報酬率
│ ├── nav_*.csv # 各再平衡頻率 NAV
│ ├── stats.json # 績效指標
│ └── summary.csv
├── debug_one_period.py # 🧪 單期除錯工具（看某一期怎麼算）
├── engine/ # 🧠 核心引擎
│ ├── data_loader.py # 讀 Excel + 對齊月資料
│ ├── return_model.py # 預期報酬模型（對齊 notebook）
│ ├── risk_model.py # 共變異數估計（Ledoit-Wolf）
│ ├── optimizer.py # Markowitz / Sortino 最佳化
│ ├── constraints.py # 投組限制
│ ├── backtest.py # 動態回測引擎
│ ├── config.py # 讀取 config.yaml
│ └── utils.py # 工具函式
├── report/
│ └── metrics.py # 📊 績效計算（Sharpe / MDD / CAGR）
└── ui/
└── app.py # 🖥️ Web UI

```

---

# 📈 預期報酬模型（Return Model）

## 股票報酬拆解（完全對齊 notebook）

```

Expected Return =
盈餘成長率 (5y EPS CAGR)

* 平均股利率
* 估值回歸 ((EPS * AvgPE - Price) / Price)

```

意義：

- 盈餘成長：公司長期競爭力
- 股利：現金流
- 估值回歸：買貴 / 買便宜的修正

---

## 債券報酬模型

```

E_ret = YTM - Duration × (ForecastYield - Y10)

```

反映：

- 持有利息
- 利率變動造成的價格影響

---

## 產業報酬模型（CAPM）

```

E_ret = BondYield + Beta × SPX_Expected_Return

```

Beta 用 rolling 5 年回歸：

```

(Industry - RF) ~ (SPX - RF)

```

---

# 📉 風險模型（Risk Model）

使用：

```

Ledoit-Wolf Shrinkage Covariance

```

好處：

- 小樣本穩定
- 不容易出現不可逆矩陣
- 比單純 sample covariance 穩定

---

# ⚙️ 投組最佳化（Optimizer）

目前實際使用：

```

EfficientSemivariance(...).max_quadratic_utility(2)

```

特性：

- 等價於「Sortino + 風險厭惡係數」
- 比 Sharpe 更重視下行風險
- 可隨時切換為：
  - max_sharpe()
  - max_sortino()

---

# 🧱 限制條件（Constraints）

例如：

- 單一資產上下限
- 股票類總和 ≤ 70%
- 可加：產業下限 / 國別上限 / 債券下限

---

# 🔁 回測引擎（Backtest）

支援：

- 月 / 季 / 年 / 半年 再平衡
- 權重 forward-fill
- 換倉成本（可選）
- 輸出：
  - NAV
  - 月報酬
  - 權重軌跡
  - 績效指標

---

# ⚙️ 重要參數（config.yaml）

| 參數 | 意義 |
|------|------|
| start_date | 建構投組的資料起點 |
| backtest_start | 回測起始 |
| backtest_end | 回測結束 |
| lookback_months | 風險估計用幾個月 |
| rolling_years | EPS / Beta 用幾年 |
| weight_bounds | 單一資產上下限 |
| stock_type_limit | 股票類總和上限 |
| optimizer | 用 Markowitz 或 Sortino |

---

# 🚀 如何執行

## 1️⃣ 建立環境

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2️⃣ 跑完整回測

```bash
python main.py
```

輸出在：

```
outputs/
```

---

## 3️⃣ 開 UI

```bash
python ui/app.py
```

瀏覽器打開：

```
http://127.0.0.1:8501
```

---

## 4️⃣ Debug 單一期

```bash
python debug_one_period.py
```

會輸出：

* 當期 μ
* 當期 window returns
* 當期 Σ
* 當期權重

並存成：

```
debug_mu_2012_01.csv
debug_window_2012_01.csv
debug_sigma_2012_01.csv
debug_weights_2012_01.csv
```

👉 用來跟 notebook 一行一行對。

---

# 📤 outputs 檔案說明

| 檔案        | 說明               |
| ----------- | ------------------ |
| weights.csv | 每期最適權重       |
| returns.csv | 各資產月報酬       |
| nav_*.csv   | 不同再平衡頻率 NAV |
| stats.json  | 績效指標           |
| summary.csv | 總表               |

---
