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
    fig, ax = plt.subplots(figsize=(14, 5.2))

    for res, lab in zip(results_list, labels):
        series = res[rule][item]
        ax.plot(series.index, series.values, label=lab, lw=2)

    ax.legend(fontsize=11, loc="best")
    ax.grid(alpha=0.3)
    ax.tick_params(labelsize=10)
    fig.tight_layout()
    return fig


# ================== UI ==================
st.set_page_config(
    page_title="Model Portfolio Lab",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自訂樣式：針對桌面寬螢幕優化
st.markdown(
    """
    <style>
    /* 主內容：限制最大寬度避免在 4K 螢幕上拉太開，桌面常見 1440~1920 解析度都能看 */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        padding-left: 2.5rem;
        padding-right: 2.5rem;
        max-width: 1600px;
    }

    /* Sidebar：加寬給中文長標籤更多空間 */
    section[data-testid="stSidebar"] {
        min-width: 320px;
        max-width: 360px;
    }
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }

    /* 標題 */
    h1 {font-size: 1.9rem !important; margin-bottom: 0.2rem;}
    h2 {font-size: 1.25rem !important; margin-top: 0.5rem;}
    h3 {font-size: 1.1rem !important;}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {gap: 6px;}
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        padding: 0 22px;
        font-size: 1rem;
    }
    .stTabs [aria-selected="true"] {font-weight: 600;}

    /* 表格字級稍微放大 */
    div[data-testid="stDataFrame"] {font-size: 0.95rem;}

    /* Metric 卡 */
    div[data-testid="stMetric"] {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 8px;
        padding: 12px 16px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Model Portfolio 策略研究平台")
st.caption("依投資人類型自動套用約束條件，回測 Markowitz / Equal Weight / 60/40 三種策略")
st.markdown("---")

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
if profile in ["積極型投資人", "成長型投資人", "穩健型投資人", "保守型投資人"]:
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

        # 積極型：債券下限 20%
        default_bond_floor = 0.2

        # 積極型：沒有非投資級債上限
        default_non_ig_limit = 1.0 # 預設為 1.0，表示無限制

    elif profile == "成長型投資人":
        st.sidebar.info("成長型預設：\n- 股票總上限 55%\n- 單一股票/產業上限 20%\n- 債券下限 40%")

        default_rule_idx = 1 # Q
        default_obj_idx = 1 # sharpe (index 1 of ["sortino", "sharpe", "utility", "min_variance"])
        default_upper = 0.2 # 單一資產上限 20%（含股票、產業）

        # 成長型：股票總上限 55%
        default_stock_limit = 0.55

        # 成長型：債券下限 40%
        default_bond_floor = 0.4

        # 成長型：沒有非投資級債上限
        default_non_ig_limit = 1.0

    elif profile == "穩健型投資人":
        st.sidebar.info("穩健型預設：\n- 股票總上限 40%\n- 排除產業類別\n- 單一資產上限 20%\n- 債券下限 60%")

        default_rule_idx = 1 # Q
        default_obj_idx = 2 # utility (index 2)
        default_upper = 0.2 # 單一資產上限 20%

        # 穩健型：股票總上限 40%
        default_stock_limit = 0.4

        # 穩健型：債券下限 60%
        default_bond_floor = 0.6

        # 穩健型：沒有非投資級債上限
        default_non_ig_limit = 1.0

    else: # 保守型投資人
        st.sidebar.info("保守型預設：\n- 僅包含 投資級債 & 非投資級債\n- 非投資級債上限 20%\n- 股票上限 0%\n- 債券下限 100%")

        default_rule_idx = 1 # Q
        default_obj_idx = 3 # min_variance (index 3)
        default_upper = 1.0 # 單一資產可達 100% (例如全買投資級債)

        # 保守型：股票上限預設 0
        default_stock_limit = 0.0

        # 保守型：債券下限 100%
        default_bond_floor = 1.0

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

    bond_floor = st.sidebar.slider("債券總下限", 0.0, 1.0, default_bond_floor, 0.01)

    # 額外控制：非投資級債上限 (僅在保守型顯示)
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
    
    if profile == "穩健型投資人":
        base_cfg["universe"]["industry_list"] = []  # 排除產業
    
    elif profile == "保守型投資人":
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
    cfg["constraints"]["bond_type_floor"] = bond_floor
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
        st.subheader("策略績效對比表")
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
            hide_index=True,
        )

    # ---- Tab2 ----
    with tab2:
        st.subheader("淨值曲線 (NAV)")
        fig1 = plot_multiple(results_list, name_list, rule, "nav")
        st.pyplot(fig1, use_container_width=True)

        st.markdown("---")
        st.subheader("週期報酬率 (Returns)")
        fig2 = plot_multiple(results_list, name_list, rule, "returns")
        st.pyplot(fig2, use_container_width=True)

    # ---- Tab3 ----
    with tab3:
        # 改用 Target Weights (Model Weights) 而不是 Drifted Weights
        # weights_df 是每個月產生的「建議配置」，不管是否有交易
        # 用這個來檢查是否符合 constraint 最準確

        weights_all = weights_df
        if not weights_all.empty:
            latest = weights_all.iloc[-1]

            # ===== 股債比 =====
            # 注意：return_model 會把 market_list 的空格換成底線（"SPX Index" -> "SPX_Index"）
            # 所以這裡比對前要做相同 normalize；industry / bond 名稱沒被改動
            market_assets = [
                m.replace(" ", "_") for m in (cfg["universe"].get("market_list") or [])
            ]
            industry_assets = cfg["universe"].get("industry_list") or []
            bond_assets = cfg["universe"].get("bond_list") or []

            stock_cols = [c for c in latest.index if c in market_assets + industry_assets]
            bond_cols = [c for c in latest.index if c in bond_assets]

            stock_weight = float(latest[stock_cols].sum()) if stock_cols else 0.0
            bond_weight = float(latest[bond_cols].sum()) if bond_cols else 0.0

            ratio_df = pd.DataFrame(
                {"Weight": [stock_weight, bond_weight]},
                index=["股票 (Stocks)", "債券 (Bonds)"],
            )
            ratio_df.index.name = "資產類別"

            st.subheader("股債配置比例")
            st.dataframe(
                ratio_df.style.format({"Weight": "{:.2%}"}),
                width="stretch",
            )

            st.markdown("---")

            # ===== 各資產權重明細 =====
            st.subheader("各資產權重明細")
            latest_sorted = latest.sort_values(ascending=False)
            st.dataframe(
                latest_sorted.to_frame("Weight").style.format("{:.2%}"),
                width="stretch",
            )

            with st.expander("點擊展開查看全部歷史權重 (Expand Full Weight History)"):
                st.dataframe(
                    weights_all.style.format("{:.2%}"),
                    width="stretch",
                )
        else:
            st.warning("No weights data available.")
