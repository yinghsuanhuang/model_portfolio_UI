import sys
from pathlib import Path
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# ====== 修正 import path ======
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.config import load_config
from main import run_ui_pipeline

plt.rcParams['axes.unicode_minus'] = False


# ================== 工具 ==================
def plot_multiple(results_list, labels, rule, item):
    fig, ax = plt.subplots(figsize=(10, 5))

    for res, lab in zip(results_list, labels):
        series = res[rule][item]
        ax.plot(series.index, series.values, label=lab, lw=2)

    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


# ================== UI ==================
st.set_page_config(page_title="Model Portfolio Lab", layout="wide")
st.title("📊 Model Portfolio 策略研究平台")

# -------- Sidebar --------


cfg_path = st.sidebar.text_input("config.yaml 路徑", value="config.yaml")
base_cfg = load_config(cfg_path)

rule = st.sidebar.selectbox("再平衡頻率", ["M", "Q", "A", "2Q-DEC"], index=1)
objective = st.sidebar.selectbox("最佳化目標", ["sortino", "sharpe", "utility"], index=0)
upper = st.sidebar.slider("單一資產上限", 0.0, 1.0, float(base_cfg["constraints"]["upper"]), 0.01)
stock_limit = st.sidebar.slider("股票總上限", 0.0, 1.0, float(base_cfg["constraints"]["stock_type_limit"]), 0.01)
lookback = st.sidebar.selectbox("風險 lookback（月）", [12, 24, 36, 60], index=2)
rolling_year = st.sidebar.selectbox("基本面 rolling_year（年）", [3, 5, 7], index=1)
trading_cost = st.sidebar.number_input("交易成本 (bps)", value=0)

run_btn = st.sidebar.button("▶️ Run Backtest")


# ================== 主區域 ==================
if run_btn:
    cfg = base_cfg.copy()
    cfg["optimizer"]["objective"] = objective
    cfg["constraints"]["upper"] = upper
    cfg["constraints"]["stock_type_limit"] = stock_limit
    cfg["risk"]["lookback"] = lookback
    cfg["return_model"]["rolling_year"] = rolling_year
    cfg["backtest"]["trading_cost_bps"] = trading_cost

    results_list, name_list = run_ui_pipeline(cfg)
    results_marko = results_list[0]

    # ===== 績效表 =====
    rows = []
    for name, res in zip(name_list, results_list):

        nav = res[rule]["nav"]
        stats = res[rule]["stats"]

        rows.append({
            "Strategy": name,
            "Total Return": nav.iloc[-1] / nav.iloc[0] - 1,
            "CAGR": stats.get("CAGR", np.nan),
            "Sharpe": stats.get("Sharpe", np.nan),
            "Sortino": stats.get("Sortino", np.nan),
            "MDD": stats.get("max_drawdown", np.nan),
            "Calmar": stats.get("Calmar", np.nan),
        })

    df_stats = pd.DataFrame(rows)

    # ================== Tabs ==================
    tab1, tab2, tab3 = st.tabs(["績效總覽", "策略對比", "權重分析"])

    # ---- Tab1 ----
    with tab1:
        st.dataframe(
            df_stats.style.format({
                "Total Return": "{:.2%}",
                "CAGR": "{:.2%}",
                "Sharpe": "{:.2f}",
                "Sortino": "{:.2f}",
                "MDD": "{:.2%}",
                "Calmar": "{:.2f}",
            }),
            width="stretch",
        )



    # ---- Tab2 ----
    with tab2:
        fig1 = plot_multiple(results_list, name_list, rule, "nav")
        st.pyplot(fig1)

        fig2 = plot_multiple(results_list, name_list, rule, "returns")
        st.pyplot(fig2)

    # ---- Tab3 ----
    with tab3:
        weights_all = results_marko[rule]["weights"]
        latest = weights_all.iloc[-1].sort_values(ascending=False)

        st.dataframe(
            latest.to_frame("Weight").style.format("{:.2%}"),
            width="stretch",
        )

        with st.expander("展開全部權重"):
            st.dataframe(
                weights_all.style.format("{:.2%}"),
                width="stretch",
            )
