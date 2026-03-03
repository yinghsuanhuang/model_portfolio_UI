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
st.title("Model Portfolio 策略研究平台")

# -------- Sidebar --------


# -------- Sidebar --------

# 初始化變數，避免 Scope 問題導致 NameError
rule = "Q" 

st.sidebar.header("投資人設定")
profile = st.sidebar.selectbox(
    "投資人類型",
    ["積極型投資人", "成長型投資人", "穩健型投資人", "保守型投資人"]
)

# 預設行為：只有在選擇「積極型投資人」時顯示原有選項
if profile in ["積極型投資人", "成長型投資人", "保守型投資人"]:
    st.sidebar.markdown("---")
    st.sidebar.header("進階參數設定")
    
    cfg_path = st.sidebar.text_input("config.yaml 路徑", value="config.yaml")
    base_cfg = load_config(cfg_path)

    # 根據不同 Profile 設定「預設值」
    if profile == "積極型投資人":
        default_rule_idx = 1 # Q (index 1 of ["M", "Q", "A", "2Q-DEC"])
        default_obj_idx = 0 # sortino
        default_upper = float(base_cfg["constraints"]["upper"])
        
        # 積極型：股票上限讀 config (通常 0.7)
        default_stock_limit = float(base_cfg["constraints"]["stock_type_limit"])
        
        # 積極型：沒有額外的 asset_upper
        asset_upper_default = {}
        
        # 積極型：沒有非投資級債上限
        default_non_ig_limit = 1.0 # 預設為 1.0，表示無限制
        
    elif profile == "成長型投資人":
        st.sidebar.info("成長型預設：\n- 股票總上限 60%\n- 單一股票/產業上限 20%\n- 債券無限制")
        
        default_rule_idx = 1 # Q
        default_obj_idx = 1 # sharpe (index 1 of ["sortino", "sharpe", "utility", "min_variance"])
        default_upper = 0.2 # 單一資產上限 20%（含股票、產業）
        
        # 成長型：股票總上限 60%
        default_stock_limit = 0.6
        
        # 成長型：沒有額外的 asset_upper
        asset_upper_default = {}
        
        # 成長型：沒有非投資級債上限
        default_non_ig_limit = 1.0
        
    else: # 保守型投資人
        st.sidebar.info("保守型預設：\n- 僅包含 投資級債 & 非投資級債\n- 非投資級債上限 20%\n- 股票上限 0%")
        
        default_rule_idx = 1 # Q
        default_obj_idx = 3 # min_variance (index 3)
        default_upper = 1.0 # 單一資產可達 100% (例如全買投資級債)
        
        # 保守型：股票上限預設 0
        default_stock_limit = 0.0
        
        # 保守型：非投資級債上限預設 20%
        default_non_ig_limit = 0.2

    # -------------------------------------------------------------------------
    # 2. 顯示並獲取參數 (Display and Get Parameters)
    # -------------------------------------------------------------------------
    
    # (A) Rebalance Frequency
    rule_options = ["M", "Q", "A", "2Q-DEC"]
    rule_map = {"M": "Monthly", "Q": "Quarterly", "A": "Annually", "2Q-DEC": "Semi-Annual (Jun/Dec)"}
    
    rule = st.sidebar.selectbox(
        "再平衡頻率 (Rebalance Freq)",
        rule_options,
        index=default_rule_idx,
        format_func=lambda x: f"{x} ({rule_map[x]})",
        key=f"sb_rule_{profile}"
    )

    # (B) Objective Function
    obj_options = ["sortino", "sharpe", "utility", "min_variance"]
    obj_map = {
        "sortino": "Max Sortino Ratio",
        "sharpe": "Max Sharpe Ratio", 
        "utility": "Max Utility (Risk Aversion)",
        "min_variance": "Min Variance (Min Volatility)"
    }
    
    obj_func = st.sidebar.selectbox(
        "最佳化目標 (Objective)",
        obj_options,
        index=default_obj_idx,
        format_func=lambda x: obj_map[x],
        key=f"sb_obj_{profile}"
    )
    objective = obj_func # Assign to 'objective' for downstream compatibility

    upper = st.sidebar.slider("單一資產上限", 0.0, 1.0, default_upper, 0.01)
    
    stock_limit = st.sidebar.slider("股票總上限", 0.0, 1.0, default_stock_limit, 0.01)
    
    # 額外控制：非投資級債上限 (僅在保守型顯示，或總是顯示但預設 None?)
    # 為了簡潔，只在保守型顯示這個特有參數
    hy_bond_limit = 1.0
    if profile == "保守型投資人":
        hy_bond_limit = st.sidebar.slider("非投資級債上限", 0.0, 1.0, default_non_ig_limit, 0.01)
    
    lookback = st.sidebar.selectbox("風險 lookback（月）", [12, 24, 36, 60], index=2)
    rolling_year = st.sidebar.selectbox("基本面 rolling_year（年）", [3, 5, 7], index=1)
    trading_cost = st.sidebar.number_input("交易成本 (bps)", value=0)

    run_btn = st.sidebar.button("▶️ Run Backtest")

    # 準備執行用的 cfg (僅在 run_btn 按下後真正使用)
    # 但為了邏輯一致性，我們需在這裡定義「如果按下按鈕要怎麼改 cfg」的邏輯
    # Streamlit 的 run_btn 會觸發 rerun，所以下面的 if run_btn 會執行
    
    # 我們需要把這些變數傳遞給下面的執行區塊
    # 或是直接在這裡修改 base_cfg 對象 (注意：base_cfg 是 dict，mutable)
    
    if profile == "保守型投資人":
        base_cfg["universe"]["market_list"] = []
        base_cfg["universe"]["industry_list"] = []
        base_cfg["universe"]["bond_list"] = ["投資級債", "非投資級債"]
        
        # 使用者調整後的 hy_bond_limit
        base_cfg["constraints"]["asset_upper"] = {"非投資級債": hy_bond_limit}
        
else:
    # 其他類型的投資人目前留白
    st.sidebar.info(f"目前選擇：{profile}")
    st.sidebar.write("（此模式尚未設定，請先使用「積極型投資人」或「保守型投資人」）")
    run_btn = False


# ================== 主區域 ==================
if run_btn:
    cfg = base_cfg.copy()
    cfg["optimizer"]["objective"] = objective
    cfg["constraints"]["upper"] = upper
    cfg["constraints"]["stock_type_limit"] = stock_limit
    cfg["risk"]["lookback"] = lookback
    cfg["return_model"]["rolling_year"] = rolling_year
    cfg["backtest"]["trading_cost_bps"] = trading_cost

    with st.spinner("🚀 正在執行回測運算中，請稍候... (Running Backtest...)"):
        results_list, name_list, weights_df = run_ui_pipeline(cfg)

    st.success("✅ 回測完成！ (Backtest Completed!)")
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
        # 改用 Target Weights (Model Weights) 而不是 Drifted Weights
        # weights_df 是每個月產生的「建議配置」，不管是否有交易
        # 用這個來檢查是否符合 constraint 最準確
        
        weights_all = weights_df
        if not weights_all.empty:
            latest = weights_all.iloc[-1].sort_values(ascending=False)

            st.dataframe(
                latest.to_frame("Weight").style.format("{:.2%}"),
                use_container_width=True,
            )

            # Spacer removed
            with st.expander("點擊展開查看全部歷史權重 (Expand Full Weight History)"):
                st.dataframe(
                    weights_all.style.format("{:.2%}"),
                    use_container_width=True,
                )
        else:
            st.warning("No weights data available.")
