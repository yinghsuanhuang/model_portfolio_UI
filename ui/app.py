import sys
import copy
import tempfile
import argparse
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# ── CLI argument: --ai-provider nlg|gemini|sonnet|opus ──────
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--ai-provider", default="gemini",
                     choices=["nlg", "gemini", "sonnet", "opus"])
_cli_args, _ = _parser.parse_known_args()
AI_PROVIDER = _cli_args.ai_provider

# ====== 修正 import path ======
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.config import load_config
from engine.data_loader import load_taa_data
from engine.taa import compute_reference_signal, _multiplier


@st.cache_data(show_spinner=False)
def get_reference_signal(eff_taa_path, backtest_end, nfp, pmi, p1, z, m1):
    """試算參考期訊號（X 無關），用於決定 ΔX 滑桿上限。"""
    mini_cfg = {
        "dates": {"backtest_end": backtest_end},
        "taa": {
            "nfp_threshold": nfp, "pmi_threshold": pmi,
            "valuation_multipliers": {"plus_1": p1, "zero": z, "minus_1": m1},
        },
    }
    taa_data = load_taa_data(mini_cfg, override_path=eff_taa_path)
    return compute_reference_signal(taa_data, mini_cfg, nfp, pmi)

@st.cache_data(show_spinner=False)
def _get_return_date_range(path_str: str) -> tuple:
    """快速掃描 RETURN 工作表，回傳 (最早月, 最晚月) 字串 "YYYY-MM"。"""
    try:
        xl = pd.ExcelFile(path_str)
        norm = {s.strip().lower(): s for s in xl.sheet_names}
        sheet = norm.get("return")
        if sheet is None:
            return None, None
        idx = pd.read_excel(path_str, sheet_name=sheet, header=1,
                            index_col=0, usecols=[0]).index
        idx = pd.to_datetime(idx).sort_values().dropna()
        return idx[0].strftime("%Y-%m"), idx[-1].strftime("%Y-%m")
    except Exception:
        return None, None


plt.rcParams['axes.unicode_minus'] = False

# ====== 色彩 token（漲跌/策略一致配色）======
C_UP = "#005BAC"      # 加碼 / 正（凱基藍）
C_DOWN = "#ED6C00"    # 減碼 / 負（凱基橘）
C_FLAT = "#9aa0a6"    # 中性
C_MEETING = "#b7791f" # 會議討論（琥珀）


# ================== 工具 ==================
STRAT_COLORS = {
    "Markowitz": "#1f77b4",      # 藍
    "SAA + TAA": "#ff7f0e",      # 橘（虛線）
    "Equal Weight": "#7e57c2",   # 紫（原綠，避免漲跌語意）
    "60/40": "#6c757d",          # 灰（原紅，避免漲跌語意）
}


def plot_multiple(results_list, labels, rule, item):
    fig, ax = plt.subplots(figsize=(14, 5.2))
    for res, lab in zip(results_list, labels):
        series = res[rule][item]
        color = STRAT_COLORS.get(lab)
        if lab == "SAA + TAA":
            ax.plot(series.index, series.values, label=lab, lw=2.2,
                    ls="--", color=color, zorder=5)
        else:
            ax.plot(series.index, series.values, label=lab, lw=2, color=color)
    ax.legend(fontsize=11, loc="best")
    ax.grid(alpha=0.3)
    ax.tick_params(labelsize=10)
    fig.tight_layout()
    return fig


def _score_color(v):
    try:
        if v > 0:
            return f"color:{C_UP};font-weight:600"
        if v < 0:
            return f"color:{C_DOWN};font-weight:600"
    except TypeError:
        pass
    return f"color:{C_FLAT}"


def render_signal_cards(latest):
    direction = int(latest["direction"])
    macro = int(latest["macro_score"])
    erp = int(latest["erp_score"])
    above = bool(latest["market_above_10MA"])
    dx = float(latest["delta_x"])

    def signed(v):
        return f"{v:+d}" if v != 0 else "0"

    def col(sentiment):  # sentiment ∈ {1, 0, -1}
        return {1: C_UP, 0: C_FLAT, -1: C_DOWN}[sentiment]

    dx_sent = 1 if dx > 0 else -1 if dx < 0 else 0

    # 統一結構：(標籤, 大數值, 數值色, 副標說明)
    cards = [
        ("總體面分數", signed(macro), col(direction),
         {1: "加碼 ▲", 0: "維持 ―", -1: "減碼 ▼"}[direction]),
        ("市場面 (SPX vs 200MA)", "多頭" if above else "空頭", col(1 if above else -1),
         "月底收盤價 &gt; 200MA" if above else "月底收盤價 &lt; 200MA"),
        ("評價分數 (ERP)", signed(erp), col(erp),
         {1: "股市相對便宜", 0: "正常", -1: "股市相對昂貴"}[erp]),
        ("本期 ΔX", f"{dx * 100:+.1f}%", col(dx_sent),
         {1: "加碼", 0: "不調整", -1: "減碼"}[dx_sent]),
    ]

    html = '<div class="taa-cards">'
    for lbl, val, vcol, sub in cards:
        html += (
            f'<div class="taa-card"><div class="lbl">{lbl}</div>'
            f'<div class="val" style="color:{vcol}">{val}</div>'
            f'<div class="sub">{sub}</div></div>'
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def plot_delta_x(signals_df):
    fig, ax = plt.subplots(figsize=(14, 3.4))
    vals = signals_df["delta_x"] * 100.0
    colors = [C_UP if v > 0 else C_DOWN if v < 0 else C_FLAT for v in vals]
    ax.bar(signals_df.index, vals, width=22, color=colors)
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_ylabel("ΔX (%)", fontsize=10)
    ax.grid(alpha=0.25, axis="y")
    ax.tick_params(labelsize=9)
    fig.tight_layout()
    return fig


# ================== UI ==================
st.set_page_config(
    page_title="Model Portfolio Lab",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem; padding-bottom: 2rem;
        padding-left: 2.5rem; padding-right: 2.5rem;
        max-width: 1600px;
    }
    section[data-testid="stSidebar"] { min-width: 320px; max-width: 360px; }
    section[data-testid="stSidebar"] .block-container {
        padding-top: 1rem; padding-left: 1rem; padding-right: 1rem;
    }
    h1 {font-size: 1.9rem !important; margin-bottom: 0.2rem;}
    h2 {font-size: 1.25rem !important; margin-top: 0.5rem;}
    h3 {font-size: 1.1rem !important;}
    .stTabs [data-baseweb="tab-list"] {gap: 6px;}
    .stTabs [data-baseweb="tab"] {height: 44px; padding: 0 22px; font-size: 1rem;}
    .stTabs [aria-selected="true"] {font-weight: 600;}
    div[data-testid="stDataFrame"] {font-size: 0.95rem;}
    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #e9ecef;
        border-radius: 8px; padding: 12px 16px;
    }
    /* TAA 當期訊號卡（四張統一樣式）*/
    .taa-cards { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:6px 0 2px; }
    .taa-card { background:#f8f9fa; border:1px solid #e9ecef; border-radius:10px;
                padding:16px 18px; display:flex; flex-direction:column; }
    .taa-card .lbl { font-size:0.82rem; color:#80868b; margin-bottom:8px;
                     white-space:nowrap; letter-spacing:.02em; }
    .taa-card .val { font-size:1.85rem; font-weight:800; line-height:1.15; }
    .taa-card .sub { font-size:0.9rem; font-weight:500; margin-top:7px; color:#5f6368; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Model Portfolio 策略研究平台")
st.caption("SAA 戰略配置 + TAA 戰術調整：依投資人類型套用約束，回測並對比多種策略")
st.markdown("---")

# -------- Sidebar --------
rule = "Q"

# === 資料來源 ===
st.sidebar.header("資料來源")
DEFAULT_DATA_PATH = ROOT / "data" / "SAA_RawData.xlsx"

uploaded_file = st.sidebar.file_uploader(
    "上傳 SAA_RawData (Excel)", type=["xlsx"],
    help="每月更新此檔可取代預設資料；未上傳則使用 repo 內預設檔。",
)
if uploaded_file is not None:
    tmp = tempfile.NamedTemporaryFile(prefix="saa_uploaded_", suffix=".xlsx", delete=False)
    tmp.write(uploaded_file.getvalue()); tmp.close()
    data_path = Path(tmp.name)
    st.sidebar.success(f"使用上傳檔案：{uploaded_file.name}")
else:
    data_path = DEFAULT_DATA_PATH
    if data_path.exists():
        st.sidebar.caption(f"使用預設檔案：data/{data_path.name}")
    else:
        st.sidebar.error(f"預設檔案不存在：{data_path}")

taa_uploaded = st.sidebar.file_uploader(
    "上傳 TAA_RawData (Excel)", type=["xlsx"], key="taa_upload",
    help="TAA 三因子原始資料；未上傳則使用 data/TAA_RawData.xlsx。",
)
if taa_uploaded is not None:
    tmp2 = tempfile.NamedTemporaryFile(prefix="taa_uploaded_", suffix=".xlsx", delete=False)
    tmp2.write(taa_uploaded.getvalue()); tmp2.close()
    taa_data_path = str(Path(tmp2.name))
    st.sidebar.success(f"使用上傳檔案：{taa_uploaded.name}")
else:
    taa_data_path = None

st.sidebar.markdown("---")

st.sidebar.header("投資人設定")
profile = st.sidebar.selectbox(
    "投資人類型",
    ["積極型投資人", "成長型投資人", "穩健型投資人", "保守型投資人"]
)

run_btn = st.sidebar.button("▶️ Run Backtest", type="primary", width='stretch')

st.sidebar.markdown("---")
st.sidebar.header("進階參數設定")
cfg_path = st.sidebar.text_input("config.yaml 路徑", value="config.yaml")
base_cfg = load_config(cfg_path)

# ----- 回測時間窗口 -----
_data_min, _data_max = _get_return_date_range(str(data_path))
_cfg_start = base_cfg["dates"]["backtest_start"][:7]
_cfg_end   = base_cfg["dates"]["backtest_end"][:7]
if _data_min and _data_max:
    _months = [str(m) for m in pd.period_range(_data_min, _data_max, freq="M")]
    _def_s = _cfg_start if _cfg_start in _months else _months[0]
    _def_e = _cfg_end   if _cfg_end   in _months else _months[-1]
    bt_start_ym, bt_end_ym = st.sidebar.select_slider(
        "回測時間窗口",
        options=_months,
        value=(_def_s, _def_e),
        key="bt_range",
        help="拖曳兩端控點設定回測起訖月份；範圍為資料實際可用期間。",
    )
    _n_months = len(pd.period_range(bt_start_ym, bt_end_ym, freq="M"))
    st.sidebar.caption(f"共 {_n_months} 個月（{bt_start_ym} ～ {bt_end_ym}）")
else:
    bt_start_ym = st.sidebar.text_input("開始 (YYYY-MM)", value=_cfg_start, key="bt_start")
    bt_end_ym   = st.sidebar.text_input("結束 (YYYY-MM)", value=_cfg_end,   key="bt_end")

# 各 Profile 預設
if profile == "積極型投資人":
    default_rule_idx, default_obj_idx = 1, 0
    default_upper = float(base_cfg["constraints"]["upper"])
    default_stock_limit = float(base_cfg["constraints"]["stock_type_limit"])
    default_bond_floor, default_non_ig_limit = 0.2, 1.0
elif profile == "成長型投資人":
    st.sidebar.info("成長型預設：\n- 股票總上限 55%\n- 單一股票/產業上限 20%\n- 債券下限 40%")
    default_rule_idx, default_obj_idx = 1, 1
    default_upper, default_stock_limit = 0.2, 0.55
    default_bond_floor, default_non_ig_limit = 0.4, 1.0
elif profile == "穩健型投資人":
    st.sidebar.info("穩健型預設：\n- 股票總上限 40%\n- 排除產業類別\n- 單一資產上限 20%\n- 債券下限 60%")
    default_rule_idx, default_obj_idx = 1, 2
    default_upper, default_stock_limit = 0.2, 0.4
    default_bond_floor, default_non_ig_limit = 0.6, 1.0
else:  # 保守型
    st.sidebar.info("保守型預設：\n- 僅含 投資級債 & 非投資級債\n- 非投資級債上限 20%\n- 股票上限 0%\n- 債券下限 100%")
    default_rule_idx, default_obj_idx = 1, 3
    default_upper, default_stock_limit = 1.0, 0.0
    default_bond_floor, default_non_ig_limit = 1.0, 0.2

rule_options = ["M", "Q", "A", "2Q-DEC"]
rule_map = {"M": "Monthly", "Q": "Quarterly", "A": "Annually", "2Q-DEC": "Semi-Annual (Jun/Dec)"}
rule = st.sidebar.selectbox(
    "再平衡頻率 (Rebalance Freq)", rule_options, index=default_rule_idx,
    format_func=lambda x: f"{x} ({rule_map[x]})", key=f"sb_rule_{profile}",
)

obj_options = ["sortino", "sharpe", "utility", "min_variance"]
obj_map = {"sortino": "Max Sortino Ratio", "sharpe": "Max Sharpe Ratio",
           "utility": "Max Utility (Risk Aversion)", "min_variance": "Min Variance"}
objective = st.sidebar.selectbox(
    "最佳化目標 (Objective)", obj_options, index=default_obj_idx,
    format_func=lambda x: obj_map[x], key=f"sb_obj_{profile}",
)

upper = st.sidebar.slider("單一資產上限", 0.0, 1.0, default_upper, 0.01)
stock_limit = st.sidebar.slider("股票總上限", 0.0, 1.0, default_stock_limit, 0.01)
bond_floor = st.sidebar.slider("債券總下限", 0.0, 1.0, default_bond_floor, 0.01)

hy_bond_limit = 1.0
if profile == "保守型投資人":
    hy_bond_limit = st.sidebar.slider("非投資級債上限", 0.0, 1.0, default_non_ig_limit, 0.01)

lookback = st.sidebar.selectbox("風險 lookback（月）", [12, 24, 36, 60], index=2)
rolling_year = st.sidebar.selectbox("基本面 rolling_year（年）", [3, 5, 7], index=1)
trading_cost = st.sidebar.number_input("交易成本 (bps)", value=0)

# === TAA 戰術調整 ===
st.sidebar.markdown("---")
st.sidebar.header("TAA 戰術調整")

taa_profile_X = base_cfg.get("taa", {}).get("profile_max_adjust", {})
taa_default_X = float(taa_profile_X.get(profile, 0.0))
taa_nfp_default = int(base_cfg.get("taa", {}).get("nfp_threshold", 50))
mult_cfg = base_cfg.get("taa", {}).get("valuation_multipliers", {})

if profile == "保守型投資人":
    st.sidebar.info("保守型不啟用 TAA（X = 0%）")
    taa_enabled, taa_X, taa_nfp = False, 0.0, taa_nfp_default
else:
    taa_enabled = st.sidebar.toggle("啟用 TAA", value=True, key=f"taa_on_{profile}")
    if taa_enabled:
        taa_nfp = st.sidebar.number_input(
            "非農就業門檻（千人）", value=taa_nfp_default, step=5,
            key=f"taa_nfp_{profile}",
            help="總體面 NFP 因子的加減碼分界，預設 5 萬（=50 千人）。",
        )

        # 試算參考期（回測末月）訊號 → 決定 ΔX 滑桿上限（X 無關）
        eff_taa_path = taa_data_path or str(ROOT / "data" / "TAA_RawData.xlsx")
        taa_X = taa_default_X
        try:
            ref = get_reference_signal(
                eff_taa_path,
                (pd.Timestamp(bt_end_ym) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"),
                float(taa_nfp), float(base_cfg["taa"].get("pmi_threshold", 50)),
                float(mult_cfg.get("plus_1", 1.0)), float(mult_cfg.get("zero", 0.75)),
                float(mult_cfg.get("minus_1", 0.5)),
            )
        except Exception as e:
            ref = None
            st.sidebar.warning(f"TAA 參考訊號試算失敗：{e}")

        if ref and ref["multiplier"] > 0:
            max_dx = taa_default_X * ref["multiplier"]
            dir_word = "加碼 ▲" if ref["direction"] > 0 else "減碼 ▼"
            ref_month = pd.Timestamp(ref["date"]).strftime("%Y-%m")
            cur_dx_pct = st.sidebar.slider(
                f"本期 ΔX 上限 (%)　[{ref_month} {dir_word}]",
                0.0, round(max_dx * 100.0, 2), round(max_dx * 100.0, 2), 0.5,
                key=f"taa_dx_{profile}",
                help=(f"模型本期建議幅度 {max_dx * 100:.1f}% 為上限（= X {taa_default_X * 100:.0f}% "
                      f"× 評價乘數 {ref['multiplier']:.2f}）。往下調＝等比例縮放整個回測的 X。"),
            )
            taa_X = (cur_dx_pct / 100.0) / ref["multiplier"]  # 反解回 X 上限
        else:
            st.sidebar.caption("本期無 TAA 訊號（方向＝0），改為調整 X 上限")
            taa_X_pct = st.sidebar.slider(
                "股債比最大調整 X (%)", 0.0, taa_default_X * 100.0, taa_default_X * 100.0, 0.5,
                key=f"taa_X_{profile}",
            )
            taa_X = taa_X_pct / 100.0
    else:
        taa_X, taa_nfp = 0.0, taa_nfp_default

# ── 會議討論手動覆寫（常駐面板，未觸發時停用）──────────────
meeting_override = None
_is_meeting = (
    taa_enabled
    and ref is not None
    and ref.get("meeting_flag", False)
)

st.sidebar.markdown("---")
if _is_meeting:
    st.sidebar.markdown(
        '<div style="background:#fff7e6;border-left:4px solid #b7791f;'
        'padding:8px 12px;border-radius:4px;font-size:.83rem;line-height:1.6">'
        '⚠ <b>會議討論</b> — 總體面與市場面相左<br>'
        '<span style="font-size:.78rem">預設跟隨量化方向；如需手動覆寫請選擇下方方向與幅度。</span>'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    st.sidebar.markdown(
        '<div style="color:#bbb;font-size:.82rem;padding:4px 2px">'
        '🔒 會議討論覆寫（當期未觸發）'
        '</div>',
        unsafe_allow_html=True,
    )

_override_label = st.sidebar.radio(
    "手動覆寫方向",
    options=["遵循量化（預設）", "加碼 ▲", "維持 ―", "減碼 ▼"],
    key=f"meeting_dir_{profile}",
    disabled=not _is_meeting,
)
if _is_meeting and _override_label != "遵循量化（預設）":
    if "維持" in _override_label:
        meeting_override = {"direction": 0, "delta_x": 0.0}
    else:
        _manual_dir = 1 if "加碼" in _override_label else -1
        _manual_dx_pct = st.sidebar.number_input(
            "手動 ΔX 幅度 (%)",
            min_value=0.0, max_value=100.0, value=5.0, step=0.5,
            key=f"meeting_dx_{profile}",
            help="自由輸入當期 ΔX 幅度，不受模型上限限制。",
        )
        meeting_override = {
            "direction": _manual_dir,
            "delta_x": _manual_dx_pct / 100.0,
        }

# Profile 對 universe / 約束的調整（沿用既有邏輯）
if profile == "穩健型投資人":
    base_cfg["universe"]["industry_list"] = []
elif profile == "保守型投資人":
    base_cfg["universe"]["market_list"] = []
    base_cfg["universe"]["industry_list"] = []
    base_cfg["universe"]["bond_list"] = ["投資級債", "非投資級債"]
    base_cfg["constraints"]["asset_upper"] = {"非投資級債": hy_bond_limit}


# ================== 執行回測（存進 session_state）==================
if run_btn:
    cfg = copy.deepcopy(base_cfg)
    cfg["optimizer"]["objective"] = objective
    cfg["constraints"]["upper"] = upper
    cfg["constraints"]["stock_type_limit"] = stock_limit
    cfg["constraints"]["bond_type_floor"] = bond_floor
    cfg["risk"]["lookback"] = lookback
    cfg["return_model"]["rolling_year"] = rolling_year
    cfg["backtest"]["trading_cost_bps"] = trading_cost
    cfg["dates"]["backtest_start"] = (pd.Timestamp(bt_start_ym) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
    cfg["dates"]["backtest_end"]   = (pd.Timestamp(bt_end_ym)   + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")

    cfg.setdefault("taa", {})
    cfg["taa"]["enabled"] = bool(taa_enabled)
    cfg["taa"]["current_X"] = float(taa_X)
    cfg["taa"]["nfp_threshold"] = float(taa_nfp)

    with st.spinner("🚀 正在執行回測運算中，請稍候..."):
        from main import run_ui_pipeline  # 延後引入以加速初始載入
        results_list, name_list, weights_df, taa_info = run_ui_pipeline(
            cfg, data_path=str(data_path), taa_data_path=taa_data_path,
            last_period_override=meeting_override,
        )

    st.session_state["run"] = dict(
        results_list=results_list, name_list=name_list,
        weights_df=weights_df, taa_info=taa_info,
        cfg=cfg, profile=profile,
    )
    st.session_state.pop("report_html", None)  # 新回測 → 清掉舊報告

    # 存 pickle 供 preview_report.py 快速預覽（不需重跑優化）
    import pickle, pathlib
    _cache = pathlib.Path(__file__).resolve().parents[1] / ".last_run.pkl"
    with open(_cache, "wb") as _f:
        pickle.dump(st.session_state["run"], _f)

# ================== 渲染（從 session_state）==================
run_data = st.session_state.get("run")

if not run_data:
    st.info("⬅️ 在左側設定投資人類型與參數，然後按 **Run Backtest** 開始。")
    st.stop()

results_list = run_data["results_list"]
name_list = run_data["name_list"]
weights_df = run_data["weights_df"]
taa_info = run_data["taa_info"]
cfg = run_data["cfg"]

c_msg, c_rep = st.columns([3, 1])
with c_msg:
    st.success(f"✅ 回測完成（{run_data['profile']}）")
with c_rep:
    if taa_info is not None:
        if st.button("📄 生成報告", width='stretch', type="primary"):
            from report_builder import build_html_report  # 延後引入
            with st.spinner("產生報告中..."):
                st.session_state["report_html"] = build_html_report(
                    run_data, rule, ai_provider=AI_PROVIDER
                )
            st.session_state["report_autoopen"] = True  # 生成後自動彈出新視窗
            st.rerun()
    else:
        st.caption("（啟用 TAA 後可生成報告）")

# ===== 報告：生成後在新視窗開啟完整 HTML；下載按鈕給想存檔的人 =====
if st.session_state.get("report_html"):
    import base64
    import streamlit.components.v1 as components
    from datetime import date

    _html = st.session_state["report_html"]
    _b64 = base64.b64encode(_html.encode("utf-8")).decode("ascii")
    _fname = f"TAA_Report_{run_data['profile']}_{date.today():%Y%m%d}.html"
    _autoopen = st.session_state.pop("report_autoopen", False)
    _auto_js = (
        "window.addEventListener('load',function(){if(!openReport()){"
        "document.getElementById('hint').style.display='inline';}});"
    ) if _autoopen else ""

    _opener = """
<div style="font-family:'Noto Sans TC',sans-serif;display:flex;align-items:center;gap:12px;">
  <button onclick="openReport()" style="background:#0f4c5c;color:#fff;border:none;
    padding:10px 20px;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;">
    🔗 開啟完整報告（新視窗）</button>
  <span id="hint" style="display:none;color:#b7791f;font-size:13px;">
    瀏覽器擋住自動彈窗，請點左側按鈕開啟。</span>
</div>
<script>
const B64="%s";
function openReport(){
  try{
    const bytes=Uint8Array.from(atob(B64),c=>c.charCodeAt(0));
    const blob=new Blob([bytes],{type:'text/html;charset=utf-8'});
    const w=window.open(URL.createObjectURL(blob),'_blank');
    return !!w;
  }catch(e){return false;}
}
%s
</script>
""" % (_b64, _auto_js)

    components.html(_opener, height=58)
    st.download_button(
        "⬇️ 下載 HTML 報告", data=_html, file_name=_fname,
        mime="text/html",
    )
    st.markdown("<hr/>", unsafe_allow_html=True)

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

# ===== Tabs =====
tab_names = ["績效總覽", "策略對比", "權重分析"]
if taa_info is not None:
    tab_names.append("TAA 訊號分析")
tabs = st.tabs(tab_names)

# ---- Tab1 績效總覽 ----
with tabs[0]:
    st.subheader(f"策略績效對比表（{rule} 再平衡）")
    def _hl_taa(row):
        return ["background-color:#fff8e1" if row["Strategy"] == "SAA + TAA" else "" for _ in row]
    st.dataframe(
        df_stats.style
            .apply(_hl_taa, axis=1)
            .format({
                "Total Return": "{:.2%}", "CAGR": "{:.2%}",
                "Sharpe": "{:.2f}", "Sortino": "{:.2f}",
                "MDD": "{:.2%}", "Calmar": "{:.2f}",
            }),
        width="stretch", hide_index=True,
    )

# ---- Tab2 策略對比 ----
with tabs[1]:
    st.subheader("淨值曲線 (NAV)")
    st.pyplot(plot_multiple(results_list, name_list, rule, "nav"), width='stretch')
    st.markdown("---")
    st.subheader("週期報酬率 (Returns)")
    st.pyplot(plot_multiple(results_list, name_list, rule, "returns"), width='stretch')

# ---- Tab3 權重分析 ----
with tabs[2]:
    if not weights_df.empty:
        latest = weights_df.iloc[-1]
        market_assets = [m.replace(" ", "_") for m in (cfg["universe"].get("market_list") or [])]
        industry_assets = cfg["universe"].get("industry_list") or []
        bond_assets = cfg["universe"].get("bond_list") or []
        stock_cols = [c for c in latest.index if c in market_assets + industry_assets]
        bond_cols = [c for c in latest.index if c in bond_assets]
        stock_weight = float(latest[stock_cols].sum()) if stock_cols else 0.0
        bond_weight = float(latest[bond_cols].sum()) if bond_cols else 0.0

        st.subheader("股債配置比例（SAA 基準，最新月）")
        ratio_df = pd.DataFrame({"Weight": [stock_weight, bond_weight]},
                                index=["股票 (Stocks)", "債券 (Bonds)"])
        ratio_df.index.name = "資產類別"
        st.dataframe(ratio_df.style.format({"Weight": "{:.2%}"}), width="stretch")

        st.markdown("---")
        if taa_info is not None:
            st.subheader("各資產權重：SAA 基準 vs TAA 調整後（最新月）")
            saa_latest = taa_info["saa_weights_df"].iloc[-1]
            taa_latest = taa_info["weights_df"].iloc[-1]
            cmp = pd.DataFrame({"SAA": saa_latest, "SAA+TAA": taa_latest})
            cmp["Δ"] = cmp["SAA+TAA"] - cmp["SAA"]
            cmp = cmp[(cmp["SAA"].abs() > 1e-9) | (cmp["SAA+TAA"].abs() > 1e-9)]
            cmp = cmp.sort_values("SAA+TAA", ascending=False)

            def _delta_color(v):
                if v > 1e-9:
                    return f"color:{C_UP};font-weight:600"
                if v < -1e-9:
                    return f"color:{C_DOWN};font-weight:600"
                return f"color:{C_FLAT}"
            st.dataframe(
                cmp.style.map(_delta_color, subset=["Δ"])
                    .format({"SAA": "{:.2%}", "SAA+TAA": "{:.2%}", "Δ": "{:+.2%}"}),
                width="stretch",
            )
        else:
            st.subheader("各資產權重明細（最新月）")
            st.dataframe(
                latest.sort_values(ascending=False).to_frame("Weight").style.format("{:.2%}"),
                width="stretch",
            )

        with st.expander("展開全部歷史權重 (SAA)"):
            st.dataframe(weights_df.style.format("{:.2%}"), width="stretch")
    else:
        st.warning("No weights data available.")

# ---- Tab4 TAA 訊號分析 ----
if taa_info is not None:
    with tabs[3]:
        sig = taa_info["signals_df"]
        latest = sig.iloc[-1]
        ldate = sig.index[-1].strftime("%Y-%m")
        n_active = int((sig["delta_x"] != 0).sum())
        n_meeting = int(sig["meeting_flag"].sum())

        st.subheader(f"當期訊號（{ldate}）　X 上限 = {taa_info['X']:.1%}")
        render_signal_cards(latest)

        if bool(latest["meeting_flag"]):
            st.warning(
                f"⚠ {ldate} 觸及「會議討論」範疇：總體面方向與市場面相左。"
                "量化版預設仍**跟隨原方向、不縮幅**執行。"
            )
        st.caption(f"全期：{n_active}/{len(sig)} 個月有調整；{n_meeting} 個月觸及會議討論範疇。")

        st.markdown("---")
        st.subheader("ΔX 時序（綠=加碼 / 紅=減碼）")
        st.pyplot(plot_delta_x(sig), width='stretch')

        st.markdown("---")
        st.subheader("歷史訊號明細")
        disp = sig.sort_index(ascending=False).copy()
        out = pd.DataFrame(index=disp.index.strftime("%Y-%m"))
        out["PMI"] = disp["pmi_score"].values
        out["NFP"] = disp["nfp_score"].values
        out["Fed"] = disp["fed_score"].values
        out["總體"] = disp["macro_score"].values
        out["方向"] = disp["direction"].map({1: "加碼", 0: "維持", -1: "減碼"}).values
        out["市場"] = disp["market_above_10MA"].map({True: ">10MA", False: "<10MA"}).values
        out["評價"] = disp["erp_score"].values
        out["乘數"] = disp["multiplier"].values
        out["ΔX"] = disp["delta_x"].values
        out["會議"] = disp["meeting_flag"].map({True: "⚠", False: ""}).values

        st.dataframe(
            out.style
                .map(_score_color, subset=["PMI", "NFP", "Fed", "總體", "評價", "ΔX"])
                .format({"乘數": "{:.2f}", "ΔX": "{:+.1%}"}),
            width="stretch", height=460,
        )
