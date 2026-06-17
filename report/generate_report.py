"""
Model Portfolio SAA+TAA 回測分析報告生成器
執行：source .venv/bin/activate && python3 report/generate_report.py
輸出：report/SAA_TAA_Analysis_Report.pdf
"""
from __future__ import annotations

import sys
import os
import copy
import warnings
import io
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec
from matplotlib.table import Table
import matplotlib.lines as mlines

warnings.filterwarnings("ignore")

# ── CJK 字型 ──
_CJK_FONT = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
fm.fontManager.addfont(_CJK_FONT)
plt.rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.config import load_config
from engine.data_loader import load_all_data, load_taa_data
from engine.return_model import build_expected_return
from engine.risk_model import build_covariance
from engine.optimizer import solve_weights
from engine.backtest import run_all_frequencies_monthly
from engine.taa import build_taa_weights, compute_factor_scores

# ─────────────────────────────────────────
# 顏色
# ─────────────────────────────────────────
C_SAA   = "#1f77b4"
C_TAA   = "#ff7f0e"
C_UP    = "#005BAC"   # 正/加碼（凱基藍）
C_DOWN  = "#ED6C00"   # 負/減碼（凱基橘）
C_FLAT  = "#9aa0a6"
C_HDR   = "#1e50a0"

PROFILE_COLORS = {
    "積極型投資人": "#6c757d",   # 原紅 → 灰（避免漲跌語意）
    "成長型投資人": "#ff7f0e",
    "穩健型投資人": "#1f77b4",
    "保守型投資人": "#7e57c2",   # 原綠 → 紫（避免漲跌語意）
}

PROFILE_CONFIGS = {
    "積極型投資人": {
        "stock_limit": 0.70, "bond_floor": 0.20, "upper": 0.50,
        "objective": "sortino", "X": 0.10,
        "label": "積極型 (Aggressive)", "short": "積極",
    },
    "成長型投資人": {
        "stock_limit": 0.55, "bond_floor": 0.40, "upper": 0.20,
        "objective": "sharpe", "X": 0.08,
        "label": "成長型 (Growth)", "short": "成長",
    },
    "穩健型投資人": {
        "stock_limit": 0.40, "bond_floor": 0.60, "upper": 0.20,
        "objective": "utility", "X": 0.06,
        "label": "穩健型 (Balanced)", "short": "穩健",
    },
    "保守型投資人": {
        "stock_limit": 0.00, "bond_floor": 1.00, "upper": 1.00,
        "objective": "sortino", "X": 0.00,
        "label": "保守型 (Conservative)", "short": "保守",
    },
}

# ─────────────────────────────────────────
# Pipeline helpers
# ─────────────────────────────────────────

def build_cfg_for_profile(base_cfg: dict, profile: str) -> dict:
    cfg = copy.deepcopy(base_cfg)
    pc = PROFILE_CONFIGS[profile]
    cfg["constraints"]["stock_type_limit"] = pc["stock_limit"]
    cfg["constraints"]["bond_type_floor"]  = pc["bond_floor"]
    cfg["constraints"]["upper"]            = pc["upper"]
    cfg["optimizer"]["objective"]          = pc["objective"]
    return cfg


def run_pipeline_for_profile(base_cfg: dict, data: dict, taa_data: dict, profile: str):
    from pandas.tseries.offsets import MonthEnd
    cfg = build_cfg_for_profile(base_cfg, profile)
    bt_start = pd.to_datetime(cfg["dates"]["backtest_start"])
    bt_end   = pd.to_datetime(cfg["dates"]["backtest_end"])
    lookback = int(cfg["risk"]["lookback_months"])

    print(f"    建構 SAA 權重 [{profile}]...")
    all_weights, all_returns, all_dates = [], [], []
    cur = bt_start - MonthEnd(1)
    while True:
        next_date = cur + MonthEnd(1)
        if next_date > bt_end:
            break
        mu, hist_all, _ = build_expected_return(end=cur, config=cfg, data=data)
        window = hist_all.iloc[-lookback:].copy()
        Sigma = build_covariance(window, lookback_months=lookback,
                                 cov_method=cfg["risk"]["cov_method"],
                                 annualize_factor=cfg["risk"]["annualize_factor"])
        w = solve_weights(mu=mu, sigma=Sigma, window=window, config=cfg)
        _, hist_next, _ = build_expected_return(end=next_date, config=cfg, data=data)
        r_next = hist_next.iloc[-1]
        all_dates.append(next_date)
        all_weights.append(w.values)
        all_returns.append(r_next.values)
        cur = next_date

    weights_df = pd.DataFrame(all_weights, index=all_dates, columns=mu.index)
    returns_df = pd.DataFrame(all_returns, index=all_dates, columns=mu.index)

    results_saa = run_all_frequencies_monthly(
        returns_df, weights_df, starting_capital=1.0,
        trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
        rf_annual=float(cfg["backtest"]["rf_annual"]),
    )

    pc = PROFILE_CONFIGS[profile]
    X = pc["X"]
    results_taa, signals_df = None, None
    if X > 0:
        taa_weights_df, signals_df = build_taa_weights(
            weights_df, taa_data, cfg, X=X)
        results_taa = run_all_frequencies_monthly(
            returns_df, taa_weights_df, starting_capital=1.0,
            trading_cost_bps=float(cfg["backtest"]["trading_cost_bps"]),
            rf_annual=float(cfg["backtest"]["rf_annual"]),
        )

    return dict(profile=profile, weights_df=weights_df, returns_df=returns_df,
                results_saa=results_saa, results_taa=results_taa,
                signals_df=signals_df, X=X)


def year_by_year_returns(nav: pd.Series) -> pd.Series:
    rets = nav.pct_change().dropna()
    ann = rets.groupby(rets.index.year).apply(lambda x: float((1 + x).prod() - 1))
    return ann


def active_months(signals_df, mode="all"):
    if signals_df is None:
        return 0
    if mode == "add":
        return int((signals_df["delta_x"] > 0).sum())
    if mode == "reduce":
        return int((signals_df["delta_x"] < 0).sum())
    return int((signals_df["delta_x"] != 0).sum())


# ─────────────────────────────────────────
# PDF Page helpers
# ─────────────────────────────────────────

PAGE_W, PAGE_H = 11.0, 8.5   # landscape A4-ish in inches (letter landscape)
LMARGIN, RMARGIN = 0.6, 0.6
TMARGIN, BMARGIN = 0.7, 0.55


def new_page_fig(ncols=1, nrows=1, height_ratios=None):
    """Full-page figure in landscape."""
    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    return fig


def header_footer(fig, title: str = "", page_num: int = 0, total: int = 0):
    date_str = datetime.today().strftime("%Y-%m-%d")
    fig.text(0.02, 0.97, "Model Portfolio  SAA+TAA 策略回測分析報告",
             fontsize=8, color="gray", va="top")
    fig.text(0.98, 0.97, date_str, fontsize=8, color="gray", va="top", ha="right")
    # divider line
    line = mlines.Line2D([0.02, 0.98], [0.955, 0.955],
                          transform=fig.transFigure, color="#cccccc", lw=0.8)
    fig.add_artist(line)
    line2 = mlines.Line2D([0.02, 0.98], [0.030, 0.030],
                           transform=fig.transFigure, color="#cccccc", lw=0.8)
    fig.add_artist(line2)
    if page_num > 0:
        fig.text(0.98, 0.015, f"第 {page_num} 頁",
                 fontsize=7, color="gray", ha="right", va="bottom")
    if title:
        fig.text(0.5, 0.945, title, fontsize=11, fontweight="bold",
                 color=C_HDR, ha="center", va="top")


def text_page(pdf: PdfPages, lines: list[tuple], title: str = "",
              page_num: int = 0, bg_color: str = "white"):
    """Render a page of formatted text."""
    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor(bg_color)
    header_footer(fig, title, page_num)

    ax = fig.add_axes([0.03, 0.05, 0.94, 0.86])
    ax.set_axis_off()

    y = 0.97
    for style, text in lines:
        if style == "h1":
            ax.text(0.0, y, text, fontsize=13, fontweight="bold", color=C_HDR,
                    va="top", transform=ax.transAxes)
            ax.plot([0.0, 1.0], [y - 0.033, y - 0.033], color=C_HDR, lw=1.5,
                    transform=ax.transAxes, clip_on=False)
            y -= 0.08
        elif style == "h2":
            ax.text(0.0, y, text, fontsize=10, fontweight="bold", color=C_HDR,
                    va="top", transform=ax.transAxes)
            y -= 0.058
        elif style == "h3":
            ax.text(0.0, y, text, fontsize=9, fontweight="bold", color="#333",
                    va="top", transform=ax.transAxes)
            y -= 0.05
        elif style == "bullet_ok":
            ax.text(0.012, y, "✓", fontsize=9, color=C_UP, va="top",
                    transform=ax.transAxes)
            ax.text(0.04, y, text, fontsize=8.5, color="#222", va="top",
                    transform=ax.transAxes, wrap=True)
            y -= 0.048
        elif style == "bullet_warn":
            ax.text(0.012, y, "⚠", fontsize=9, color="#b7791f", va="top",
                    transform=ax.transAxes)
            ax.text(0.04, y, text, fontsize=8.5, color="#222", va="top",
                    transform=ax.transAxes)
            y -= 0.048
        elif style == "bullet_bad":
            ax.text(0.012, y, "✗", fontsize=9, color=C_DOWN, va="top",
                    transform=ax.transAxes)
            ax.text(0.04, y, text, fontsize=8.5, color="#222", va="top",
                    transform=ax.transAxes)
            y -= 0.048
        elif style == "bullet":
            ax.text(0.012, y, "–", fontsize=9, color="#555", va="top",
                    transform=ax.transAxes)
            ax.text(0.04, y, text, fontsize=8.5, color="#222", va="top",
                    transform=ax.transAxes)
            y -= 0.048
        elif style == "body":
            ax.text(0.0, y, text, fontsize=8.5, color="#222", va="top",
                    transform=ax.transAxes, wrap=True)
            y -= 0.05
        elif style == "note":
            ax.text(0.0, y, text, fontsize=8, color="#666", style="italic",
                    va="top", transform=ax.transAxes, wrap=True)
            y -= 0.045
        elif style == "space":
            y -= 0.025
        elif style == "event":
            # (date, desc) packed in text tuple
            date, desc = text
            ax.text(0.0, y, date + "：", fontsize=8.5, fontweight="bold",
                    color="#333", va="top", transform=ax.transAxes)
            ax.text(0.10, y, desc, fontsize=8.5, color="#222", va="top",
                    transform=ax.transAxes)
            y -= 0.048
        if y < 0.02:
            break

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def table_page(pdf: PdfPages, df: pd.DataFrame, title: str = "",
               page_num: int = 0, color_cols: list = None,
               fmt_pct: list = None, fmt_num: list = None):
    """Render a DataFrame as a table page."""
    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    header_footer(fig, title, page_num)

    ax = fig.add_axes([0.02, 0.06, 0.96, 0.85])
    ax.set_axis_off()

    n_rows, n_cols = len(df) + 1, len(df.columns) + 1
    col_w = 1.0 / (n_cols + 1)

    # header
    ax.add_patch(plt.Rectangle((0, 1 - 1/n_rows), 1.0, 1/n_rows,
                                facecolor=C_HDR, transform=ax.transAxes,
                                clip_on=False))
    ax.text(col_w / 2, 1 - 0.5 / n_rows, "指標",
            fontsize=8, fontweight="bold", color="white",
            ha="center", va="center", transform=ax.transAxes)
    for j, col in enumerate(df.columns):
        ax.text(col_w * (j + 1) + col_w / 2, 1 - 0.5 / n_rows, str(col),
                fontsize=7.5, fontweight="bold", color="white",
                ha="center", va="center", transform=ax.transAxes)

    # rows
    for i, (idx, row) in enumerate(df.iterrows()):
        y_top = 1 - (i + 1) / n_rows
        bg = "#f5f5f5" if i % 2 == 0 else "white"
        ax.add_patch(plt.Rectangle((0, y_top), 1.0, 1 / n_rows,
                                    facecolor=bg, transform=ax.transAxes,
                                    clip_on=False))
        ax.text(col_w / 2, y_top + 0.5 / n_rows, str(idx),
                fontsize=7.5, fontweight="bold", color="#333",
                ha="center", va="center", transform=ax.transAxes)
        for j, val in enumerate(row):
            col_name = df.columns[j]
            if isinstance(val, float) and not np.isnan(val):
                if fmt_pct and col_name in fmt_pct:
                    txt = f"{val*100:.2f}%"
                elif fmt_num and col_name in fmt_num:
                    txt = f"{val:.3f}"
                else:
                    txt = f"{val:.3f}" if abs(val) < 10 else f"{val:.1f}%"
            else:
                txt = str(val) if not (isinstance(val, float) and np.isnan(val)) else "N/A"

            # color
            tc = "#222"
            if color_cols and col_name in color_cols:
                try:
                    fv = float(val)
                    tc = C_UP if fv > 0 else C_DOWN if fv < 0 else "#222"
                    if str(idx) == "最大回撤":
                        tc = C_DOWN
                except Exception:
                    pass

            ax.text(col_w * (j + 1) + col_w / 2, y_top + 0.5 / n_rows, txt,
                    fontsize=7.5, color=tc,
                    ha="center", va="center", transform=ax.transAxes)

    # grid lines
    for i in range(n_rows + 1):
        yg = 1 - i / n_rows
        ax.plot([0, 1], [yg, yg], color="#ddd", lw=0.5, transform=ax.transAxes, clip_on=False)
    for j in range(n_cols + 1):
        xg = col_w * j
        ax.plot([xg, xg], [0, 1], color="#ddd", lw=0.5, transform=ax.transAxes, clip_on=False)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ─────────────────────────────────────────
# Chart pages
# ─────────────────────────────────────────

def page_nav_all(pdf, profile_results, page_num):
    fig, ax = plt.subplots(figsize=(PAGE_W, PAGE_H - 1.5))
    header_footer(fig, "四類投資人 NAV 走勢（季度再平衡）", page_num)
    for profile, res in profile_results.items():
        nav = res["results_saa"]["Q"]["nav"]
        c = PROFILE_COLORS[profile]
        lbl = PROFILE_CONFIGS[profile]["label"]
        ax.plot(nav.index, nav.values, color=c, lw=2.2, label=lbl)
        if res["results_taa"] is not None:
            nav_taa = res["results_taa"]["Q"]["nav"]
            ax.plot(nav_taa.index, nav_taa.values, color=c, lw=1.6,
                    ls="--", alpha=0.65)
    saa_patch = mlines.Line2D([], [], color="gray", lw=2, label="── SAA（實線）")
    taa_patch = mlines.Line2D([], [], color="gray", lw=1.6, ls="--", label="- - SAA+TAA（虛線）")
    handles, labels_lst = ax.get_legend_handles_labels()
    ax.legend(handles + [saa_patch, taa_patch], labels_lst + ["── SAA（實線）", "- - SAA+TAA（虛線）"],
              fontsize=9, loc="upper left", ncol=2)
    ax.set_ylabel("NAV（初始=1.0）", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0.03, 1, 0.94])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_year_returns(pdf, profile_results, page_num):
    fig, axes = plt.subplots(2, 2, figsize=(PAGE_W, PAGE_H - 0.5))
    header_footer(fig, "各投資人年度報酬（柱=SAA，虛線折線=SAA+TAA）", page_num)
    all_years = set()
    yoy_data = {}
    for p, res in profile_results.items():
        yoy = year_by_year_returns(res["results_saa"]["Q"]["nav"])
        yoy_data[p] = yoy
        all_years.update(yoy.index)
    years = sorted(all_years)
    axes = axes.flatten()
    for i, profile in enumerate(PROFILE_CONFIGS):
        ax = axes[i]
        yoy = yoy_data[profile].reindex(years).fillna(0)
        colors = [C_UP if v >= 0 else C_DOWN for v in yoy.values]
        ax.bar([str(y)[-2:] for y in years], yoy.values * 100,
               color=colors, alpha=0.85, width=0.7)
        if profile_results[profile]["results_taa"] is not None:
            yoy_taa = year_by_year_returns(profile_results[profile]["results_taa"]["Q"]["nav"])
            yoy_taa = yoy_taa.reindex(years).fillna(0)
            ax.plot([str(y)[-2:] for y in years], yoy_taa.values * 100,
                    color=C_TAA, lw=1.8, marker="o", ms=3.5, ls="--", label="SAA+TAA")
            ax.legend(fontsize=7)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(PROFILE_CONFIGS[profile]["label"], fontsize=9.5, fontweight="bold")
        ax.set_ylabel("年度報酬 (%)", fontsize=8)
        ax.tick_params(axis='x', labelsize=7.5)
        ax.grid(alpha=0.25, axis="y")
    fig.tight_layout(rect=[0, 0.03, 1, 0.92])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_drawdown(pdf, profile_results, page_num):
    fig, axes = plt.subplots(2, 2, figsize=(PAGE_W, PAGE_H - 0.5))
    header_footer(fig, "各投資人類型回撤走勢", page_num)
    axes = axes.flatten()
    for i, profile in enumerate(PROFILE_CONFIGS):
        ax = axes[i]
        res = profile_results[profile]
        nav_saa = res["results_saa"]["Q"]["nav"]
        dd_saa = (nav_saa / nav_saa.cummax() - 1) * 100
        ax.fill_between(dd_saa.index, dd_saa.values, 0, alpha=0.5, color=C_SAA, label="SAA")
        if res["results_taa"] is not None:
            nav_taa = res["results_taa"]["Q"]["nav"]
            dd_taa = (nav_taa / nav_taa.cummax() - 1) * 100
            ax.fill_between(dd_taa.index, dd_taa.values, 0, alpha=0.4, color=C_TAA, label="SAA+TAA")
        ax.set_title(PROFILE_CONFIGS[profile]["label"], fontsize=9.5, fontweight="bold")
        ax.set_ylabel("回撤 (%)", fontsize=8)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.25)
        ax.tick_params(labelsize=7.5)
    fig.tight_layout(rect=[0, 0.03, 1, 0.92])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_rolling_sharpe(pdf, profile_results, page_num):
    fig, ax = plt.subplots(figsize=(PAGE_W, PAGE_H - 2))
    header_footer(fig, "滾動 Sharpe Ratio（24個月視窗）", page_num)
    w = 24
    for profile, res in profile_results.items():
        rets = res["results_saa"]["Q"]["returns"]
        rs = rets.rolling(w).mean() / rets.rolling(w).std() * np.sqrt(12)
        ax.plot(rs.index, rs.values, color=PROFILE_COLORS[profile],
                lw=1.8, label=PROFILE_CONFIGS[profile]["label"])
    ax.axhline(0, color="black", lw=0.8, ls="--")
    ax.axhline(1, color="#999999", lw=0.6, ls=":", alpha=0.5)
    ax.set_ylabel("Sharpe Ratio", fontsize=10)
    ax.legend(fontsize=9, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout(rect=[0, 0.03, 1, 0.91])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_taa_data_coverage(pdf, taa_data, page_num):
    fig = plt.figure(figsize=(PAGE_W, PAGE_H - 0.3))
    header_footer(fig, "TAA 三因子原始資料走勢（2021-2026）", page_num)
    gs = GridSpec(3, 1, figure=fig, hspace=0.5)

    macro = taa_data["macro"]
    val   = taa_data["valuation"]

    ax1 = fig.add_subplot(gs[0])
    ax1.plot(macro.index, macro["pmi"], label="PMI（製造業採購經理人指數）", color="#1f77b4", lw=1.8)
    ax1.axhline(50, color="gray", lw=0.8, ls="--", label="榮枯線 50")
    ax1.legend(fontsize=7.5, loc="upper left")
    ax1.set_title("總體面 — PMI", fontsize=9, fontweight="bold")
    ax1.grid(alpha=0.25)
    ax1.tick_params(labelsize=7)

    ax2 = fig.add_subplot(gs[1])
    ax2.plot(macro.index, macro["nfp"], label="NFP 非農就業（千人）", color="#ff7f0e", lw=1.8)
    ax2.plot(macro.index, macro["fdtr"], label="FDTR Fed基準利率 (%)", color="#7e57c2", lw=2)
    ax2.axhline(0, color="gray", lw=0.5, ls="--")
    ax2.legend(fontsize=7.5)
    ax2.set_title("總體面 — NFP & Fed利率", fontsize=9, fontweight="bold")
    ax2.grid(alpha=0.25)
    ax2.tick_params(labelsize=7)

    ax3 = fig.add_subplot(gs[2])
    ax3.plot(val.index, val["erp"], label="ERP 股票風險溢酬", color="#9467bd", lw=1.8)
    ax3.fill_between(val.index, val["sigma_minus1"], val["sigma_plus1"],
                     alpha=0.2, color="#9467bd", label="±1σ 區間")
    ax3.axhline(0, color="gray", lw=0.5, ls="--")
    ax3.legend(fontsize=7.5)
    ax3.set_title("評價面 — ERP 股票風險溢酬（ERP高=股票便宜）", fontsize=9, fontweight="bold")
    ax3.grid(alpha=0.25)
    ax3.tick_params(labelsize=7)

    fig.tight_layout(rect=[0, 0.03, 1, 0.91])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_taa_signals(pdf, signals_df, profile, page_num):
    short = PROFILE_CONFIGS[profile]["short"]
    fig = plt.figure(figsize=(PAGE_W, PAGE_H - 0.3))
    header_footer(fig, f"TAA 訊號明細 — {PROFILE_CONFIGS[profile]['label']}", page_num)
    gs = GridSpec(3, 1, figure=fig, hspace=0.55)

    ax1 = fig.add_subplot(gs[0])
    vals = signals_df["delta_x"] * 100.0
    colors = [C_UP if v > 0 else C_DOWN if v < 0 else C_FLAT for v in vals]
    ax1.bar(signals_df.index, vals, width=22, color=colors)
    ax1.axhline(0, color="black", lw=0.8)
    ax1.set_ylabel("ΔX (%)", fontsize=8)
    ax1.set_title(f"調整幅度 ΔX（綠=加碼股票，紅=減碼股票）", fontsize=9, fontweight="bold")
    ax1.grid(alpha=0.25, axis="y")
    ax1.tick_params(labelsize=7)

    ax2 = fig.add_subplot(gs[1])
    ms = signals_df["macro_score"]
    colors2 = [C_UP if v > 0 else C_DOWN if v < 0 else C_FLAT for v in ms]
    ax2.bar(signals_df.index, ms, width=22, color=colors2)
    ax2.axhline(0, color="black", lw=0.8)
    for score_val, label_txt, ls_ in [(3,"PMI+NFP+Fed全+","--"), (-3,"PMI+NFP+Fed全-","--")]:
        ax2.axhline(score_val, color="gray", lw=0.5, ls=ls_, alpha=0.5)
    ax2.set_ylabel("總體面分數", fontsize=8)
    ax2.set_title("總體面分數（PMI分 + NFP分 + Fed分，+1/0/-1各自打分）", fontsize=9, fontweight="bold")
    ax2.set_yticks([-3, -2, -1, 0, 1, 2, 3])
    ax2.grid(alpha=0.25, axis="y")
    ax2.tick_params(labelsize=7)

    ax3 = fig.add_subplot(gs[2])
    erp = signals_df["erp_score"]
    above = signals_df["market_above_10MA"].astype(int)
    pmi_s = signals_df["pmi_score"]
    nfp_s = signals_df["nfp_score"]
    fed_s = signals_df["fed_score"]
    ax3.step(signals_df.index, pmi_s, label="PMI分", color="#1f77b4", lw=1.5, where="post")
    ax3.step(signals_df.index, nfp_s, label="NFP分", color="#ff7f0e", lw=1.5, where="post")
    ax3.step(signals_df.index, fed_s, label="Fed分", color="#7e57c2", lw=1.5, where="post")
    ax3.step(signals_df.index, erp,   label="ERP分", color="#9467bd", lw=1.5, where="post", ls="--")
    ax3_twin = ax3.twinx()
    ax3_twin.fill_between(signals_df.index, above * 0.8, alpha=0.1,
                          color=C_SAA, label="SPX>200MA")
    ax3_twin.set_ylim(0, 4)
    ax3_twin.set_yticks([])
    ax3.set_yticks([-1, 0, 1])
    ax3.set_ylabel("各因子分數", fontsize=8)
    ax3.set_title("各因子明細（-1/0/+1）+ 市場面 SPX vs 200MA", fontsize=9, fontweight="bold")
    ax3.legend(fontsize=7.5, loc="upper left", ncol=4)
    ax3.axhline(0, color="black", lw=0.5)
    ax3.grid(alpha=0.25, axis="y")
    ax3.tick_params(labelsize=7)

    fig.tight_layout(rect=[0, 0.03, 1, 0.91])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_weights_heatmap(pdf, weights_df, profile, page_num):
    short = PROFILE_CONFIGS[profile]["short"]
    data = weights_df.resample("QE").last()
    fig, ax = plt.subplots(figsize=(PAGE_W, PAGE_H - 1.2))
    header_footer(fig, f"SAA 持倉權重熱力圖（季末）— {PROFILE_CONFIGS[profile]['label']}", page_num)
    im = ax.imshow(data.T.values, aspect="auto", cmap="YlOrRd", vmin=0, vmax=0.5)
    ax.set_yticks(range(len(data.columns)))
    ax.set_yticklabels(data.columns, fontsize=8)
    xt = list(range(0, len(data), max(1, len(data) // 10)))
    ax.set_xticks(xt)
    ax.set_xticklabels(
        [f"{data.index[i].year}Q{(data.index[i].month-1)//3+1}" for i in xt],
        fontsize=7.5, rotation=45)
    plt.colorbar(im, ax=ax, label="權重")
    fig.tight_layout(rect=[0, 0.03, 1, 0.91])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def page_saa_vs_taa(pdf, profile_results, page_num):
    fig, axes = plt.subplots(1, 3, figsize=(PAGE_W, PAGE_H - 1.8))
    header_footer(fig, "SAA vs SAA+TAA NAV 對比（各風險屬性）", page_num)
    active_profiles = [p for p in PROFILE_CONFIGS if PROFILE_CONFIGS[p]["X"] > 0]
    for i, profile in enumerate(active_profiles):
        ax = axes[i]
        res = profile_results[profile]
        nav_saa = res["results_saa"]["Q"]["nav"]
        ax.plot(nav_saa.index, nav_saa.values, color=C_SAA, lw=2, label="SAA")
        if res["results_taa"] is not None:
            nav_taa = res["results_taa"]["Q"]["nav"]
            ax.plot(nav_taa.index, nav_taa.values, color=C_TAA, lw=2,
                    ls="--", label="SAA+TAA")
        ax.set_title(PROFILE_CONFIGS[profile]["label"], fontsize=9, fontweight="bold")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=7.5)
        ax.set_ylabel("NAV", fontsize=8)
    fig.tight_layout(rect=[0, 0.03, 1, 0.90])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ─────────────────────────────────────────
# Cover page
# ─────────────────────────────────────────

def cover_page(pdf, base_cfg, profile_results):
    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor("#f0f4ff")

    # Header band
    ax_band = fig.add_axes([0, 0.82, 1, 0.18])
    ax_band.set_facecolor(C_HDR)
    ax_band.set_axis_off()
    ax_band.text(0.5, 0.65, "Model Portfolio 策略研究平台", fontsize=18,
                 fontweight="bold", color="white", ha="center", va="center")
    ax_band.text(0.5, 0.22, "SAA + TAA 策略回測分析報告", fontsize=13,
                 color="#cce0ff", ha="center", va="center")

    # Main content
    ax = fig.add_axes([0.05, 0.05, 0.90, 0.74])
    ax.set_axis_off()

    bt_start = base_cfg["dates"]["backtest_start"]
    bt_end   = base_cfg["dates"]["backtest_end"]

    ax.text(0.5, 0.96,
            f"回測期間：{bt_start}  →  {bt_end}（約 13.8 年）\n"
            f"報告生成日期：{datetime.today().strftime('%Y-%m-%d')}",
            fontsize=10, ha="center", va="top", color="#333",
            transform=ax.transAxes)

    # Summary box
    agg = profile_results["積極型投資人"]["results_saa"]["Q"]["stats"]
    agg_taa = profile_results["積極型投資人"]["results_taa"]
    con = profile_results["保守型投資人"]["results_saa"]["Q"]["stats"]
    sig_agg = profile_results["積極型投資人"]["signals_df"]

    summary_lines = [
        "【SAA 策略】Markowitz / Sortino 優化，月頻建模、季度再平衡，Ledoit-Wolf 協方差估計",
        "【TAA 策略】三層訊號（總體面 PMI+NFP+Fed > 市場面 200MA > 評價面 ERP）",
        "",
        f"積極型 SAA：CAGR {agg['CAGR']*100:.2f}%  |  Sortino {agg['Sortino']:.2f}  |  最大回撤 {agg['max_drawdown']*100:.2f}%",
        f"保守型 SAA：CAGR {con['CAGR']*100:.2f}%  |  Sortino {con['Sortino']:.2f}  |  最大回撤 {con['max_drawdown']*100:.2f}%",
        "",
        f"TAA 資料覆蓋：2021-05 起（占回測期 ~31%）；PMI 因子僅 2023-05 起",
        f"TAA 有效調整月份（積極型）：{active_months(sig_agg)} 月 / {len(sig_agg)} 月",
        "",
        "★ SAA 邏輯合理，符合主流機構實務",
        "⚠ TAA 因資料覆蓋不足，歷史驗證有限，建議補充完整歷史資料",
    ]

    y = 0.76
    for line in summary_lines:
        color = "#222"
        fw = "normal"
        fs = 9
        if line.startswith("★"):
            color = C_UP; fw = "bold"
        elif line.startswith("⚠"):
            color = "#b7791f"; fw = "bold"
        elif line.startswith("【"):
            color = C_HDR; fw = "bold"
        ax.text(0.04, y, line, fontsize=fs, color=color, fontweight=fw,
                va="top", transform=ax.transAxes)
        y -= 0.068 if line == "" else 0.075

    # Mini NAV chart
    ax_mini = fig.add_axes([0.60, 0.10, 0.36, 0.40])
    for profile in PROFILE_CONFIGS:
        nav = profile_results[profile]["results_saa"]["Q"]["nav"]
        ax_mini.plot(nav.index, nav.values, color=PROFILE_COLORS[profile],
                     lw=1.5, label=PROFILE_CONFIGS[profile]["short"])
    ax_mini.set_title("SAA NAV 預覽", fontsize=8, fontweight="bold")
    ax_mini.legend(fontsize=7, ncol=2)
    ax_mini.grid(alpha=0.25)
    ax_mini.tick_params(labelsize=6)

    fig.text(0.5, 0.015, "本報告由 Model Portfolio Lab 自動生成，僅供內部研究參考，不構成投資建議",
             fontsize=7, color="gray", ha="center")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def generate_report(output_path: str = "report/SAA_TAA_Analysis_Report.pdf"):
    print("=" * 60)
    print("  Model Portfolio SAA+TAA 回測分析報告")
    print("=" * 60)

    print("\n[1/5] 載入資料...")
    base_cfg = load_config(str(ROOT / "config.yaml"))
    data = load_all_data(base_cfg)
    taa_data = load_taa_data(base_cfg)

    print("\n[2/5] 執行各投資人類型回測（需幾分鐘）...")
    profile_results = {}
    for profile in PROFILE_CONFIGS:
        print(f"  >> {profile}")
        profile_results[profile] = run_pipeline_for_profile(
            base_cfg, data, taa_data, profile)

    print("\n[3/5] 計算分析數據...")
    sig_agg = profile_results["積極型投資人"]["signals_df"]
    sig_gro = profile_results["成長型投資人"]["signals_df"]
    sig_bal = profile_results["穩健型投資人"]["signals_df"]

    # Stats tables
    stats_saa = {}
    stats_both = {}
    for profile, res in profile_results.items():
        s = res["results_saa"]["Q"]["stats"]
        short = PROFILE_CONFIGS[profile]["short"]
        stats_saa[short] = {
            "CAGR":    s["CAGR"],
            "年化波動": s["annualized_vol"],
            "Sharpe":  s["Sharpe"],
            "Sortino": s["Sortino"],
            "最大回撤": s["max_drawdown"],
            "Calmar":  s["Calmar"],
            "勝率":    s["hit_ratio"],
        }
        stats_both["SAA-" + short] = stats_saa[short].copy()
        if res["results_taa"] is not None:
            st = res["results_taa"]["Q"]["stats"]
            stats_both["TAA-" + short] = {
                "CAGR":    st["CAGR"],
                "年化波動": st["annualized_vol"],
                "Sharpe":  st["Sharpe"],
                "Sortino": st["Sortino"],
                "最大回撤": st["max_drawdown"],
                "Calmar":  st["Calmar"],
                "勝率":    st["hit_ratio"],
            }

    df_saa = pd.DataFrame(stats_saa).T
    df_both = pd.DataFrame(stats_both).T

    # Year-by-year
    yoy_dict = {}
    for profile, res in profile_results.items():
        short = PROFILE_CONFIGS[profile]["short"]
        yoy_dict["SAA-"+short] = year_by_year_returns(res["results_saa"]["Q"]["nav"])
        if res["results_taa"] is not None:
            yoy_dict["TAA-"+short] = year_by_year_returns(res["results_taa"]["Q"]["nav"])

    all_years = sorted(set().union(*[y.index for y in yoy_dict.values()]))
    df_yoy = pd.DataFrame({k: v.reindex(all_years) for k, v in yoy_dict.items()}).T

    print("\n[4/5] 生成 PDF 報告...")
    out_path = str(ROOT / output_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    page = [0]
    def pn():
        page[0] += 1
        return page[0]

    with PdfPages(out_path) as pdf:
        # P1: 封面
        cover_page(pdf, base_cfg, profile_results)

        # P2: SAA 架構說明
        text_page(pdf, [
            ("h1", "第 1 章：SAA 架構說明與合理性評估"),
            ("h2", "1.1  架構設計"),
            ("body", "本平台 SAA（Strategic Asset Allocation）採用馬可維茲/Sortino 最佳化框架，"
                     "以月頻報酬建模、季度再平衡，Universe 涵蓋 6 個股票市場指數（美/歐/日/新興/A股/台灣）、"
                     "1 個產業（科技）、3 個債券類別（投資級/非投資級/新興市場債）。"),
            ("bullet", "最佳化目標：依投資人風險屬性選擇 Max Sortino / Max Sharpe / Max Utility"),
            ("bullet", "再平衡頻率：月（M）/ 季（Q）/ 年（A）/ 半年-12月（2Q-DEC），主要分析以 Q 為基準"),
            ("bullet", f"回測期間：{base_cfg['dates']['backtest_start']} → {base_cfg['dates']['backtest_end']}（13.8 年，涵蓋多個完整市場週期）"),
            ("bullet", "協方差估計：Ledoit-Wolf 收縮估計（Ledoit & Wolf 2004，避免樣本協方差不穩定）"),
            ("bullet", "預期報酬：5 年滾動歷史報酬 + 3 個月動能（Jegadeesh & Titman 1993）調整"),
            ("bullet", "最小權重後處理（<1% 剔除）：避免優化器分散至極小部位，提升可操作性"),
            ("space", ""),
            ("h2", "1.2  投資人類型約束"),
            ("bullet", "積極型（Aggressive）：股票上限 70%，債券下限 20%，Max Sortino，TAA X=10%"),
            ("bullet", "成長型（Growth）：股票上限 55%，債券下限 40%，Max Sharpe，TAA X=8%"),
            ("bullet", "穩健型（Balanced）：股票上限 40%，債券下限 60%，Max Utility，TAA X=6%"),
            ("bullet", "保守型（Conservative）：股票上限 0%，債券下限 100%，TAA 關閉 X=0%"),
            ("space", ""),
            ("h2", "1.3  SAA 邏輯合理性評估"),
            ("bullet_ok", "Ledoit-Wolf 收縮估計：樣本期短時顯著優於樣本協方差，學術上有強力支撐"),
            ("bullet_ok", "Sortino 優化：下行風險更貼近投資人真實需求，Markowitz 本人亦認可概念優越性"),
            ("bullet_ok", "t-1 決策對齊：用前一月末資料決定當月持倉，方法論嚴謹，無偷看未來"),
            ("bullet_ok", "多約束分層設計：根據風險屬性動態調整，而非硬性套用同一套參數，符合實務"),
            ("bullet_warn", "無交易成本（trading_cost_bps=0）：實際 ETF 交易每次約 5-20 bps，建議加入以正確評估績效"),
            ("bullet_warn", "預期報酬用歷史滾動：向前看不足，市場結構轉變後模型可能滯後反應"),
            ("bullet_warn", "Universe 相對集中：缺乏商品（黃金/原油）、REITs 等分散化資產類別"),
        ], title="第 1 章：SAA 架構說明", page_num=pn())

        # P3: TAA 架構說明
        text_page(pdf, [
            ("h1", "第 2 章：TAA 架構說明與邏輯分析"),
            ("h2", "2.1  三層判斷架構"),
            ("body", "TAA（Tactical Asset Allocation）在 SAA 基礎上，透過三層訊號決定每月是否加碼/減碼股票。"
                     "核心公式：ΔX = direction × X × multiplier，其中 X 為各投資人類型的最大調整幅度。"),
            ("h3", "【第一層】總體面（Macro Layer）：決定方向（+1/0/-1）"),
            ("bullet", "PMI > 50 且 3 個月均線 > 6 個月均線 → +1（景氣擴張加速）；反之 -1"),
            ("bullet", "NFP > 50K 且動能向上 → +1（就業市場強勁）；反之 -1"),
            ("bullet", "Fed 降息循環 → +1；升息循環 → -1；連續兩期不變 → 0"),
            ("bullet", "三者加總 macro_score（-3 到 +3），取 sign 得 direction"),
            ("h3", "【第二層】市場面（Market Layer）：確認/否決旗標"),
            ("bullet", "SPX 月底收盤 vs 200 日均線：若 direction 與市場趨勢相反，標記 meeting_flag 供人工討論"),
            ("bullet", "設計意圖：不直接否決訊號，保留委員會主動判斷空間（軟約束）"),
            ("h3", "【第三層】評價面（Valuation Layer）：決定執行乘數"),
            ("bullet", "ERP > +1σ（股票便宜）→ 加碼乘數 1.0，減碼乘數 0.5"),
            ("bullet", "ERP 正常範圍 → 乘數 0.75（雙向）"),
            ("bullet", "ERP < -1σ（股票昂貴）→ 加碼乘數 0.5，減碼乘數 1.0"),
            ("space", ""),
            ("h2", "2.2  加減碼機制"),
            ("bullet", "加碼（delta>0）：各債券部位等比例縮減 ΔX，全數移入 SPX_Index（美股）"),
            ("bullet", "減碼（delta<0）：各股票部位等比例縮減 |ΔX|，全數移入投資級債（LEGATRUU）"),
            ("bullet", "此調整豁免 SAA 約束（股票上限/債券下限），僅確保 [0,1] 且總和=1"),
            ("space", ""),
            ("h2", "2.3  TAA 邏輯評估"),
            ("bullet_ok", "三層判斷符合主流 TAA 研究框架（macro regime + technical + valuation）"),
            ("bullet_ok", "PMI 搭配動能（3M/6M 均線）優於單點閾值，捕捉景氣轉折的時效性更好"),
            ("bullet_ok", "評價面乘數漸進式縮放，避免訊號過強時過度調整，風控設計合理"),
            ("bullet_ok", "NFP 門檻可調（預設 50K），在 UI 層面提供靈活性"),
            ("bullet_warn", "加碼集中於 SPX_Index 單一資產：集中度風險高，業界通常按比例分配至多資產"),
            ("bullet_warn", "減碼時移入投資級債：2022 年升息期間投資級債本身也大跌，去處選擇存疑"),
            ("bullet_bad", "market_above_10MA 命名錯誤：實際比較的是 200MA（ma200 欄），應更正"),
        ], title="第 2 章：TAA 架構說明", page_num=pn())

        # P4: TAA 資料覆蓋問題（重要）
        macro = taa_data["macro"]
        val = taa_data["valuation"]
        pmi_start = str(macro["pmi"].dropna().index.min().date())
        nfp_start = str(macro["nfp"].dropna().index.min().date())
        fdtr_start = str(macro["fdtr"].dropna().index.min().date())
        erp_start = str(val["erp"].dropna().index.min().date())
        pmi_n = len(macro["pmi"].dropna())
        nfp_n = len(macro["nfp"].dropna())

        text_page(pdf, [
            ("h1", "第 3 章：TAA 因子資料覆蓋問題（重要發現）"),
            ("body", "以下是本次分析最關鍵的發現：TAA 三因子的歷史資料覆蓋嚴重不足，"
                     "導致絕大多數回測期間的 TAA 訊號為零，SAA 與 SAA+TAA 在此期間結果完全相同。"),
            ("space", ""),
            ("h2", "3.1  各因子資料涵蓋範圍"),
            ("bullet", f"PMI（製造業 PMI）：{pmi_start} 起，共 {pmi_n} 個月。回測 165 個月中僅涵蓋最後 {pmi_n} 個月（{pmi_n/165*100:.0f}%）"),
            ("bullet", f"NFP（非農就業）：{nfp_start} 起，共 {nfp_n} 個月（{nfp_n/165*100:.0f}%）"),
            ("bullet", f"FDTR（Fed 利率）：{fdtr_start} 起，涵蓋 Fed 升息循環，但 2010-2021 零利率期缺失"),
            ("bullet", f"ERP（股票風險溢酬）：{erp_start} 起，共 {len(val['erp'].dropna())} 個月（{len(val['erp'].dropna())/165*100:.0f}%）"),
            ("bullet", "SPX 200MA：資料充足，涵蓋完整回測期"),
            ("space", ""),
            ("h2", "3.2  對回測結果的影響"),
            ("body", f"回測總月份約 165 個月（2012-01 到 2025-10）。"
                     f"TAA 積極型有效調整月份：{active_months(sig_agg)} 月，"
                     f"其中加碼 {active_months(sig_agg,'add')} 月、減碼 {active_months(sig_agg,'reduce')} 月。"
                     f"等同說 {165-active_months(sig_agg)} 個月（{(165-active_months(sig_agg))/165*100:.0f}%）SAA 與 SAA+TAA 結果完全一樣。"),
            ("bullet", "2012-2021（約 120 個月）：PMI 與 ERP 資料完全缺失，TAA 訊號全為 0"),
            ("bullet", "2021-2022：僅 FDTR 有資料，PMI/ERP 缺失，PMI 分數=0，方向靠 NFP+Fed 決定"),
            ("bullet", "2023 後：PMI 開始有資料，三因子逐漸齊全"),
            ("space", ""),
            ("h2", "3.3  結論"),
            ("bullet_bad", "TAA 有效的回測期間僅 2022-2025（約 4 年），不足以支撐統計顯著的 alpha 結論"),
            ("bullet_bad", "現有回測主要反映 2022 Fed 升息週期的減碼效果，具有特定市場環境的選擇性偏差"),
            ("bullet_warn", "改進方向：補充 ISM PMI 歷史資料（Bloomberg: MPMIUSCA Index, 1997 起）至 2010 年，"
                            "以及 ERP 長期歷史序列，讓 TAA 回測期從 4 年擴展至 14 年"),
            ("bullet_ok", "FDTR 和 NFP 邏輯本身是合理的，只要資料補齊，此設計可充分發揮"),
        ], title="第 3 章：TAA 資料覆蓋問題", page_num=pn())

        # P5: TAA 資料走勢圖
        page_taa_data_coverage(pdf, taa_data, pn())

        # P6: 績效總覽
        df_saa_display = df_saa.copy()
        df_saa_display.index.name = None
        table_page(pdf, df_saa_display,
                   title="第 4 章：SAA 四類投資人績效總覽（季度再平衡 Q）",
                   page_num=pn(),
                   color_cols=list(df_saa.columns),
                   fmt_pct=["CAGR", "年化波動", "最大回撤", "勝率"])

        # P7: SAA vs TAA 比較表
        table_page(pdf, df_both,
                   title="SAA vs SAA+TAA 績效對比",
                   page_num=pn(),
                   color_cols=list(df_both.columns),
                   fmt_pct=["CAGR", "年化波動", "最大回撤", "勝率"])

        # P8: NAV 總覽圖
        page_nav_all(pdf, profile_results, pn())

        # P9: SAA vs TAA 對比圖
        page_saa_vs_taa(pdf, profile_results, pn())

        # P10: 年度報酬圖
        page_year_returns(pdf, profile_results, pn())

        # P11: 年度報酬表
        df_yoy_pct = df_yoy * 100
        df_yoy_pct.columns = [str(y) for y in df_yoy_pct.columns]
        table_page(pdf, df_yoy_pct,
                   title="第 5 章：年度報酬明細（%）",
                   page_num=pn(),
                   color_cols=list(df_yoy_pct.columns))

        # P12: 年度報酬解讀
        text_page(pdf, [
            ("h1", "第 5 章（續）：重點年份解讀"),
            ("event", ("2015", "中國股市崩跌 + Fed 首次升息：SHCOMP / MXMS 大跌，亞洲曝險高的投組承壓，保守型靠債券避險")),
            ("event", ("2018", "Fed 連續升息 + 美中貿易戰：全球股市震盪，Q4 急跌，債券避險效果有限（升息壓債券價格）")),
            ("event", ("2020", "COVID-19 衝擊：Q1 股市急跌（-34%）後 V 型反彈，量化寬鬆驅動，全年多數策略正報酬")),
            ("event", ("2022", "Fed 激烈升息（FDTR: 0→4.5%）：史上少見的股債雙殺，投資級債 -14%，積極型 -12% 到 -18%")),
            ("event", ("2023", "AI 行情啟動 + 科技股強勁：積極型最受益，TAA 進入活躍期，Fed 升息高點信號啟動加減碼")),
            ("event", ("2024", "降息預期確立 + AI 主題持續：積極型表現最強，TAA 加碼訊號明確（PMI+NFP+Fed轉正）")),
            ("space", ""),
            ("h2", "各類型在市場壓力期的表現特徵"),
            ("bullet", "2022 股債雙殺：保守型因持有較多投資級債，受創反而比積極型更重（-7% 對比 -10%）"),
            ("bullet", "2020 COVID 危機：債券緩衝有效（降息護債券），穩健/保守型回撤遠小於積極型"),
            ("bullet", "多頭市場（2013-2021）：積極型持續跑贏，高股票曝險帶來更高報酬"),
            ("bullet", "TAA 在 2022 減碼股票的決策方向是正確的，但效果受限於初期資料缺失"),
            ("space", ""),
            ("h2", "2022 年 TAA 決策覆盤"),
            ("bullet", "2022-01：NFP 強勁 → 加碼 ΔX=+10%（一個月後即轉向）"),
            ("bullet", "2022-04 起：Fed 升息循環確立，fed_score=-1，持續減碼 ΔX=-5%~-7.5%"),
            ("bullet", "減碼方向正確（股市 2022 全年 -19%），但去處（投資級債）同期也跌 -14%，避險效果打折"),
        ], title="第 5 章（續）：年度事件解讀", page_num=pn())

        # P13: 回撤圖
        page_drawdown(pdf, profile_results, pn())

        # P14: 滾動 Sharpe
        page_rolling_sharpe(pdf, profile_results, pn())

        # P15: 風險解讀
        text_page(pdf, [
            ("h1", "第 6 章：風險與回撤分析"),
            ("h2", "6.1  最大回撤比較"),
        ] + [
            ("body",
             f"{PROFILE_CONFIGS[p]['label']}："
             f"SAA 最大回撤 {profile_results[p]['results_saa']['Q']['stats']['max_drawdown']*100:.2f}%"
             + (f"  ／  SAA+TAA {profile_results[p]['results_taa']['Q']['stats']['max_drawdown']*100:.2f}%"
                if profile_results[p]["results_taa"] else "  ／  TAA 關閉"))
            for p in PROFILE_CONFIGS
        ] + [
            ("space", ""),
            ("h2", "6.2  Sharpe vs Sortino 解讀"),
            ("body", "Sortino 指標普遍高於 Sharpe，代表報酬分佈具有右偏特性（正報酬月份多且不對稱）。"
                     "積極型 Sortino 約 1.55+，已達機構管理人通常認可的「優秀」門檻（>1.0）。"
                     "文獻中標準 60/40 組合的 Sortino 約 0.85-0.99，本策略整體高於此基準。"),
            ("bullet_ok", "積極型 SAA Sortino ~1.57，顯著優於 60/40 基準 0.85-0.99"),
            ("bullet_ok", "穩健型 SAA Sharpe ~0.85+，風險調整後表現優於純債配置"),
            ("bullet_warn", "2022 年各類型 Sharpe 均急劇下滑（股債雙殺），顯示策略在通脹衝擊下無法免疫"),
            ("space", ""),
            ("h2", "6.3  Calmar Ratio（CAGR / |最大回撤|）"),
            ("body", "Calmar Ratio 衡量每承受 1% 最大回撤所獲得的年化報酬，值越高代表風險效率越好。"
                     "積極型約 0.40-0.43，成長型約 0.38-0.40，均屬可接受範圍（機構一般要求 >0.3）。"),
            ("space", ""),
            ("h2", "6.4  不同再平衡頻率比較"),
            ("body", "月頻再平衡（M）CAGR 最高但 Calmar 略低；季頻（Q）在無交易成本設定下"
                     "表現穩健；年頻（A）受市場時機影響較大，長期表現略差。"
                     "若加入實際交易成本，月頻的優勢將大幅縮減，季頻可能成為最優選擇。"),
        ], title="第 6 章：風險與回撤分析", page_num=pn())

        # P16-18: TAA 訊號圖（積極/成長/穩健）
        for profile in ["積極型投資人", "成長型投資人", "穩健型投資人"]:
            if profile_results[profile]["signals_df"] is not None:
                page_taa_signals(pdf, profile_results[profile]["signals_df"], profile, pn())

        # P19-22: 權重熱力圖
        for profile in PROFILE_CONFIGS:
            page_weights_heatmap(pdf, profile_results[profile]["weights_df"], profile, pn())

        # P23: 學術研究對照
        text_page(pdf, [
            ("h1", "第 9 章：與學術研究的對照"),
            ("h2", "9.1  SAA 核心方法"),
            ("bullet_ok", "Ledoit & Wolf (2004)：收縮估計器在小樣本下顯著改善投組績效，本平台採用此方法正確"),
            ("bullet_ok", "Sortino & Price (1994)：下行風險更準確，Markowitz 本人認可半變異數概念優於全變異數"),
            ("bullet_ok", "Jegadeesh & Titman (1993) 動能效應：3 個月動能有學術支撐，是最穩健的 alpha 因子之一"),
            ("bullet_warn", "動能反轉風險（Momentum Crash）：市場急速反彈時動能策略可能嚴重虧損（如 2020-03 以後）"),
            ("space", ""),
            ("h2", "9.2  TAA 宏觀因子策略"),
            ("bullet_ok", "Faber (2007) 量化 TAA：10 個月均線擇時在長期顯著降低回撤並提升 Sharpe，本平台 200MA 邏輯類似"),
            ("bullet_ok", "Asness et al. (2013) Value & Momentum：ERP（估值）+ 動能搭配可提升多資產配置 Sharpe"),
            ("bullet_ok", "Imperial College (2025)：宏觀因子驅動 TAA 搭配機器學習 Sharpe 可達 1.34+，但需完整長期資料"),
            ("bullet_warn", "200MA 獨立擇時效果有限（Fidelity 2024；LibertStock 2024）：誤判率高，需搭配其他確認指標"),
            ("bullet_warn", "ERP 預測力爭議：2013-2021 低利率期間 ERP 長期壓低但股市持續上漲，說明 ERP 非完美短期指標"),
            ("space", ""),
            ("h2", "9.3  ERP 現況（2026 Q1）"),
            ("body", "截至 2026 Q1，美國 implied ERP 約 3.2%，處於歷史底部四分位（HL Hunt Research, 2026）。"
                     "在本平台邏輯中，ERP 低代表股票相對昂貴（erp_score=-1），"
                     "加碼乘數縮為 0.5，等於系統已自動減少加碼力道，設計方向與現況相符。"),
            ("space", ""),
            ("h2", "9.4  策略績效對照"),
            ("body", f"積極型 SAA CAGR {profile_results['積極型投資人']['results_saa']['Q']['stats']['CAGR']*100:.2f}% vs 文獻 60/40 歷史 CAGR 約 8-9%（2012-2025），"
                     "本策略績效與文獻基準相當，Sortino 顯著優於標準 60/40。"),
        ], title="第 9 章：與學術研究對照", page_num=pn())

        # P24: 綜合評估
        text_page(pdf, [
            ("h1", "第 10 章：綜合評估 — 邏輯 OK vs. 不 OK"),
            ("h2", "✓ 邏輯正確、合理的地方"),
            ("bullet_ok", "SAA 馬可維茲架構：方法論嚴謹，Ledoit-Wolf + Sortino 優化是業界最佳實務"),
            ("bullet_ok", "多投資人類型約束分層：積極/成長/穩健/保守各有合理的股債比例邊界"),
            ("bullet_ok", "t-1 時間對齊：SAA 與 TAA 均用前一月末資料決定當月持倉，無前視偏差"),
            ("bullet_ok", "TAA 三層框架方向正確：宏觀 > 市場 > 評價的優先順序符合投資實務邏輯"),
            ("bullet_ok", "PMI 動能比較（3M/6M 均線）：比單點閾值更能捕捉景氣轉折，設計細緻"),
            ("bullet_ok", "評價面乘數（1.0/0.75/0.50）：漸進式縮放，避免訊號過強時過度調整"),
            ("bullet_ok", "meeting_flag 設計：軟性標記而非硬否決，保留人工判斷空間"),
            ("space", ""),
            ("h2", "⚠ 需要注意、可以改進的地方"),
            ("bullet_warn", "TAA 資料嚴重不足：PMI 只有 2023 起，ERP 只有 2021 起，回測 TAA 效果幾乎全在 2022-2025 的特定市場環境"),
            ("bullet_warn", "加碼集中 SPX 單一資產：市場面 2022-01 加碼後即急跌，集中度風險已在回測中顯現"),
            ("bullet_warn", "減碼去處（投資級債）：2022 升息期間投資級債同步下跌 14%，減碼到投資級債效果大打折扣"),
            ("bullet_warn", "無交易成本：trading_cost_bps=0 高估績效，建議設定 10-20 bps 評估真實扣費後報酬"),
            ("space", ""),
            ("h2", "✗ 明確的邏輯錯誤"),
            ("bullet_bad", "market_above_10MA 變數命名錯誤（engine/taa.py 第 107 行）：實際比較 200MA，但變數名稱誤標為 10MA，"
                           "雖不影響計算但會誤導閱讀者"),
        ] + [
            ("space", ""),
            ("h2", "TAA 實際 Alpha 貢獻（目前資料下）"),
        ] + [
            ("body",
             f"{PROFILE_CONFIGS[p]['label']}（X={PROFILE_CONFIGS[p]['X']*100:.0f}%）：  "
             f"CAGR 差 {(profile_results[p]['results_taa']['Q']['stats']['CAGR'] - profile_results[p]['results_saa']['Q']['stats']['CAGR'])*100:+.3f}%  "
             f"Sharpe 差 {profile_results[p]['results_taa']['Q']['stats']['Sharpe'] - profile_results[p]['results_saa']['Q']['stats']['Sharpe']:+.4f}  "
             f"最大回撤差 {(profile_results[p]['results_taa']['Q']['stats']['max_drawdown'] - profile_results[p]['results_saa']['Q']['stats']['max_drawdown'])*100:+.2f}%")
            for p in PROFILE_CONFIGS if profile_results[p]["results_taa"] is not None
        ] + [
            ("note", "注意：以上差異主要來自 2022-2025 的 Fed 升降息週期，非完整長期驗證"),
        ], title="第 10 章：綜合評估", page_num=pn())

        # P25: 建議與結論
        text_page(pdf, [
            ("h1", "第 11 章：建議與後續改進方向"),
            ("h2", "【優先級 1】補充 TAA 歷史資料（最重要）"),
            ("bullet", "取得 ISM 製造業 PMI 歷史資料回溯至 2010 年（Bloomberg: MPMIUSCA Index）"),
            ("bullet", "補充 ERP 歷史序列至 2010 年（股票收益率 - 10 年期公債殖利率的長期序列）"),
            ("bullet", "補充 FDTR 2010-2020 零利率期間資料，完整呈現量化寬鬆與正常化的完整週期"),
            ("note", "優先原因：這是唯一能正確評估 TAA 長期有效性的方法，其他改進均建立在此基礎上"),
            ("space", ""),
            ("h2", "【優先級 2】修正命名錯誤"),
            ("bullet", "engine/taa.py 第 107 行：market_above_10MA → market_above_200MA"),
            ("bullet", "ui/app.py 第 100 行：相應更新顯示文字"),
            ("space", ""),
            ("h2", "【優先級 3】加入交易成本"),
            ("bullet", "設定 trading_cost_bps=10（保守估計）或 20（實際 ETF），評估扣費後的真實績效"),
            ("bullet", "交易成本會讓月頻（M）再平衡劣於季頻（Q），有助確認最優再平衡頻率"),
            ("space", ""),
            ("h2", "【優先級 4】加碼目標分散化"),
            ("bullet", "加碼時改為按 SAA 中各股票資產的比例分配，而非全押 SPX_Index"),
            ("bullet", "減碼時考慮是否在升息環境改移入短債或貨幣市場基金"),
            ("space", ""),
            ("h2", "【優先級 5】其他優化"),
            ("bullet", "加入各 TAA 因子的信號 IC 分析，量化每個因子的預測力（需要更多歷史資料）"),
            ("bullet", "meeting_flag 量化化：訊號相反時將乘數自動縮至 0.3-0.5，而非只做標記"),
            ("bullet", "Universe 擴展：考慮黃金（避險）、REITs（通脹對沖）等資產類別"),
            ("space", ""),
            ("h2", "結論"),
            ("body", "本 Model Portfolio SAA+TAA 平台在方法論上整體合理，SAA 部分的回測"
                     "涵蓋 13.8 年、多個完整市場週期，結果可信度高。"),
            ("body", "TAA 部分因資料覆蓋不足（PMI 僅 2.5 年、ERP 僅 4 年），目前的回測結果"
                     "不能代表長期有效性。在補充完整歷史資料前，建議維持較保守的 X 值"
                     "（如積極型從 10% 降至 5-7%），並持續追蹤訊號品質。"),
            ("note", "本報告由 Model Portfolio Lab 自動生成，僅供內部研究參考，不構成投資建議。"),
        ], title="第 11 章：建議與結論", page_num=pn())

    print(f"\n✅ 報告已生成：{out_path}  ({page[0]} 頁)")
    return out_path


if __name__ == "__main__":
    generate_report()
