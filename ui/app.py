import sys
from pathlib import Path
import subprocess
import tempfile
import yaml
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

# ====== 修正 import path ======
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.config import load_config
from main import run_ui_pipeline

# ================== 畫圖工具 ==================
plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'Microsoft JhengHei', 'Noto Sans CJK TC', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

def plot_multiple(results_list, labels, rule, item='nav', title='策略對比', ylabel='NAV'):
    fig, ax = plt.subplots(figsize=(10,5))
    for res, lab in zip(results_list, labels):
        series = res[rule][item]
        if isinstance(series, pd.DataFrame):
            # weights_out
            for col in series.columns:
                ax.plot(series.index, series[col], label=col)
        else:
            ax.plot(series.index, series.values, label=lab, lw=2)

    ax.set_title(title)
    ax.set_xlabel("日期")
    ax.set_ylabel(ylabel)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig

# ================== UI ==================
st.set_page_config(page_title="Model Portfolio Lab", layout="wide")
st.title("📊 Model Portfolio 策略研究平台")

# -------- Sidebar --------
st.sidebar.header("⚙️ 參數設定")

cfg_path = st.sidebar.text_input("config.yaml 路徑", value="config.yaml")
base_cfg = load_config(cfg_path)

rule = st.sidebar.selectbox("再平衡頻率", ["M","Q","A","2Q-DEC"], index=1)

objective = st.sidebar.selectbox("最佳化目標", ["sortino","sharpe","utility"], index=0)
upper = st.sidebar.slider("單一資產上限 upper", 0.0, 1.0, float(base_cfg["constraints"]["upper"]), 0.01)
stock_limit = st.sidebar.slider("股票總上限 stock_type_limit", 0.0, 1.0, float(base_cfg["constraints"]["stock_type_limit"]), 0.01)

lookback = st.sidebar.selectbox("風險 lookback（月）", [12,24,36,60], index=2)
rolling_year = st.sidebar.selectbox("基本面 rolling_year（年）", [3,5,7], index=1)

trading_cost = st.sidebar.number_input("交易成本 (bps)", value=0)

st.sidebar.markdown("---")
run_btn = st.sidebar.button("▶️ Run Backtest")

# -------- 主區域 --------
if run_btn:
    st.info("⏳ 計算中，請稍候...")

    # ====== 組新 config ======
    cfg = base_cfg.copy()
    cfg["optimizer"]["objective"] = objective
    cfg["constraints"]["upper"] = upper
    cfg["constraints"]["stock_type_limit"] = stock_limit
    cfg["risk"]["lookback"] = lookback
    cfg["risk"]["rolling_year"] = rolling_year
    cfg["backtest"]["trading_cost_bps"] = trading_cost

    results_list, name_list = run_ui_pipeline(cfg)
    results_marko = results_list[0]

    # ====== 組績效表 ======
    rows = []
    for name, res in zip(name_list, results_list):
        stats = res[rule]["stats"]
        rows.append({
            "Strategy": name,
            "CAGR": stats["CAGR"],
            "Sharpe": stats["Sharpe"],
            "Sortino": stats["Sortino"],
            "MDD": stats["max_drawdown"],
            "Calmar": stats["Calmar"],
        })
    df_stats = pd.DataFrame(rows)

    # ====== Tabs ======
    tab1, tab2, tab3 = st.tabs(["績效總覽", "策略對比", "權重分析"])

    with tab1:
        st.subheader("績效指標比較")
        st.dataframe(df_stats.style.format({
            "CAGR":"{:.2%}",
            "Sharpe":"{:.2f}",
            "Sortino":"{:.2f}",
            "MDD":"{:.2%}",
            "Calmar":"{:.2f}",
        }))

    with tab2:
        st.subheader("NAV 對比")
        fig1 = plot_multiple(results_list, name_list, rule, item="nav", title="NAV 對比", ylabel="NAV")
        st.pyplot(fig1)

        st.subheader("每期報酬對比")
        fig2 = plot_multiple(results_list, name_list, rule, item="returns", title="每期報酬率", ylabel="Return")
        st.pyplot(fig2)

    with tab3:
        st.subheader("Markowitz 權重變化")
        fig3 = plot_multiple([results_marko], ["Markowitz"], rule, item="weights", title="權重時間序列", ylabel="Weight")
        st.pyplot(fig3)

    st.success("✅ 回測完成！")

else:
    st.info("請在左側調整參數後，點擊 ▶️ Run Backtest")
