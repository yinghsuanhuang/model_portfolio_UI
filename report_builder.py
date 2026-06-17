"""
TAA 一頁式 HTML 報告產生器（編輯排版 + 互動 Plotly）。
由 ui/app.py 的「生成報告」按鈕呼叫：build_html_report(run_data, rule) -> HTML 字串。
與 report/generate_report.py（PDF）無關，互不影響。
"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path
import pandas as pd
from pandas.tseries.offsets import MonthEnd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PLOTLYJS_CDN = "https://cdn.plot.ly/plotly-3.5.0.min.js"

ASSET_LABELS = {
    "SPX_Index": "標普500 (美股)",
    "SXXP_Index": "STOXX 歐洲",
    "NKY_Index": "日經 (日股)",
    "MXMS_Index": "MSCI 新興市場",
    "SHCOMP_Index": "上證綜合",
    "TWSE_Index": "台股加權",
    "科技": "科技 (產業)",
    "投資級債": "投資級債",
    "非投資級債": "非投資級債",
    "新興市場債": "新興市場債",
}

# 詳細權重表用的顯示名稱與分類
_ASSET_DISPLAY = {
    "SPX_Index":   "美國（S&P 500）",
    "SXXP_Index":  "歐洲（STOXX 600）",
    "NKY_Index":   "日本（日經）",
    "MXMS_Index":  "新興市場（MSCI）",
    "SHCOMP_Index":"中國（上證）",
    "TWSE_Index":  "台灣（加權）",
    "科技":        "科技",
    "投資級債":    "投資級債",
    "非投資級債":  "非投資級債",
    "新興市場債":  "新興市場債",
}
_ASSET_CAT = {
    "SPX_Index": "地區", "SXXP_Index": "地區", "NKY_Index": "地區",
    "MXMS_Index": "地區", "SHCOMP_Index": "地區", "TWSE_Index": "地區",
    "科技": "產業",
    "投資級債": "資產", "非投資級債": "資產", "新興市場債": "資產",
}
_CAT_ORDER = {"地區": 0, "產業": 1, "資產": 2}

C_UP, C_DOWN, C_FLAT = "#005BAC", "#ED6C00", "#8a8f98"  # 凱基藍=正/加碼、橘=負/減碼
C_INK, C_ACCENT, C_PAPER = "#1a1a1a", "#0f4c5c", "#ffffff"

STRAT_LABEL = {"Markowitz": "SAA 基準", "SAA + TAA": "SAA+TAA", "60/40": "股六債四基準"}
STRAT_COLOR = {"Markowitz": "#1f77b4", "SAA + TAA": "#ff7f0e", "60/40": "#9aa0a6"}

_PLOT_LAYOUT = dict(
    template="plotly_white",
    margin=dict(l=48, r=20, t=30, b=36),
    font=dict(family="Noto Sans TC, sans-serif", size=12, color=C_INK),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)


def _fig_html(fig) -> str:
    return fig.to_html(include_plotlyjs=False, full_html=False,
                       config={"displayModeBar": False, "responsive": True})


def _buckets(cfg, idx):
    market = [m.replace(" ", "_") for m in (cfg["universe"].get("market_list") or [])]
    industry = cfg["universe"].get("industry_list") or []
    bonds = cfg["universe"].get("bond_list") or []
    stock_cols = [c for c in idx if c in market + industry]
    bond_cols = [c for c in idx if c in bonds]
    return stock_cols, bond_cols


def _asof(df, when):
    sub = df.loc[:when]
    return sub.iloc[-1] if not sub.empty else None


# ============================================================
# Plotly 圖
# ============================================================

def _fig_nav(results_list, name_list, rule):
    fig = go.Figure()
    by_name = dict(zip(name_list, results_list))
    for name in ["Markowitz", "SAA + TAA", "60/40"]:
        if name not in by_name:
            continue
        nav = by_name[name][rule]["nav"]
        fig.add_trace(go.Scatter(
            x=nav.index, y=nav.values, name=STRAT_LABEL[name],
            line=dict(color=STRAT_COLOR[name], width=2.4,
                      dash="dash" if name == "SAA + TAA" else "solid"),
            hovertemplate="%{x|%Y-%m}<br>%{y:.3f}<extra></extra>",
        ))
    fig.update_layout(height=340, yaxis_title="淨值 (起始=1)", **_PLOT_LAYOUT)
    return _fig_html(fig)


def _fig_market(market_df):
    df = market_df.dropna()
    df = df.loc[df.index >= (df.index.max() - pd.DateOffset(years=7))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["spx"], name="S&P 500",
                             line=dict(color=C_ACCENT, width=2),
                             hovertemplate="%{x|%Y-%m}<br>SPX %{y:.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=df.index, y=df["ma200"], name="10月均線 (200日)",
                             line=dict(color="#bbb", width=1.6, dash="dot"),
                             hovertemplate="%{x|%Y-%m}<br>MA %{y:.0f}<extra></extra>"))
    fig.update_layout(height=300, **_PLOT_LAYOUT)
    return _fig_html(fig)


def _fig_erp(val_df):
    df = val_df.dropna(subset=["erp"])
    df = df.loc[df.index >= (df.index.max() - pd.DateOffset(years=5))]
    p1   = float(df["sigma_plus1"].iloc[-1])
    m1   = float(df["sigma_minus1"].iloc[-1])
    mean = (p1 + m1) / 2
    fig = go.Figure()
    fig.add_hrect(y0=m1, y1=p1, fillcolor="rgba(120,120,120,0.10)", line_width=0)
    fig.add_trace(go.Scatter(x=df.index, y=df["erp"], name="ERP (%)",
                             line=dict(color=C_ACCENT, width=2),
                             hovertemplate="%{x|%Y-%m}<br>ERP %{y:.2f}%<extra></extra>"))
    fig.add_hline(y=mean, line=dict(color="#888", width=1.2, dash="dot"),
                  annotation_text="均值", annotation_position="top left")
    fig.add_hline(y=p1, line=dict(color=C_UP, width=1, dash="dash"),
                  annotation_text="+1σ（相對便宜）", annotation_position="top left")
    fig.add_hline(y=m1, line=dict(color=C_DOWN, width=1, dash="dash"),
                  annotation_text="-1σ（相對昂貴）", annotation_position="bottom left")
    fig.update_layout(height=300, yaxis_title="股權風險溢酬 (%)", **_PLOT_LAYOUT)
    return _fig_html(fig)


def _fig_donut(saa_latest, taa_latest, cfg):
    s_cols, b_cols = _buckets(cfg, saa_latest.index)
    saa_s, saa_b = float(saa_latest[s_cols].sum()), float(saa_latest[b_cols].sum())
    taa_s, taa_b = float(taa_latest[s_cols].sum()), float(taa_latest[b_cols].sum())
    delta = taa_s - saa_s

    STOCK_C = C_ACCENT   # "#0f4c5c"
    BOND_C  = "#c9ced6"

    fig = make_subplots(rows=1, cols=2, specs=[[{"type": "domain"}, {"type": "domain"}]],
                        subplot_titles=("調整前 (SAA)", "調整後 (SAA+TAA)"))

    # Left donut: SAA baseline
    fig.add_trace(go.Pie(
        labels=["股票", "固定收益"], values=[saa_s, saa_b], name="SAA",
        hole=0.55, sort=False,
        marker=dict(colors=[STOCK_C, BOND_C]),
        textinfo="label+percent", textfont=dict(size=12),
        title=dict(text=f"股 {saa_s:.0%}", font=dict(size=16)),
        hovertemplate="%{label} %{percent:.0%}<extra></extra>",
    ), 1, 1)

    # Right donut: TAA — delta portion uses a distinct highlight color
    if abs(delta) > 1e-3:
        if delta > 0:
            # Added stocks: base stock (dark) + TAA delta (blue) + bonds
            taa_labels = ["股票", f"TAA加碼{delta:.0%}", "固定收益"]
            taa_values = [saa_s, delta, taa_b]
            taa_colors = [STOCK_C, C_UP, BOND_C]
        else:
            # Reduced stocks: remaining stocks + base bonds + TAA delta (orange)
            taa_labels = ["股票", "固定收益", f"TAA減碼{abs(delta):.0%}"]
            taa_values = [taa_s, saa_b, abs(delta)]
            taa_colors = [STOCK_C, BOND_C, C_DOWN]
        title_col = C_UP if delta > 0 else C_DOWN
    else:
        taa_labels = ["股票", "固定收益"]
        taa_values = [taa_s, taa_b]
        taa_colors = [STOCK_C, BOND_C]
        title_col = STOCK_C

    # TAA segment 標籤已含 %，其餘 segment 補上百分比
    _total = sum(taa_values)
    taa_text = [
        lbl if lbl.startswith("TAA") else f"{lbl} {v/_total:.0%}"
        for lbl, v in zip(taa_labels, taa_values)
    ]
    fig.add_trace(go.Pie(
        labels=taa_labels, values=taa_values, name="TAA",
        hole=0.55, sort=False,
        marker=dict(colors=taa_colors),
        text=taa_text, textinfo="text", textfont=dict(size=12),
        title=dict(text=f"股 {taa_s:.0%}", font=dict(size=16, color=title_col)),
        hovertemplate="%{label} %{percent:.0%}<extra></extra>",
    ), 1, 2)

    fig.update_layout(height=300, showlegend=False,
                      margin=dict(l=10, r=10, t=40, b=10),
                      font=dict(family="Noto Sans TC, sans-serif", color=C_INK),
                      paper_bgcolor="rgba(0,0,0,0)")
    return _fig_html(fig)


# ============================================================
# HTML 區塊
# ============================================================

def _scorecard_html(last, mrow, mas):
    def cell(score):
        c = C_UP if score > 0 else C_DOWN if score < 0 else C_FLAT
        return f'<span class="score" style="color:{c}">{score:+d}</span>' if score else \
               f'<span class="score" style="color:{C_FLAT}">0</span>'

    def read(score):
        return {1: "支持加碼", 0: "中性", -1: "支持減碼"}[int(score)]

    def badge(score, text):
        c  = C_UP if score > 0 else C_DOWN if score < 0 else C_FLAT
        bg = "#e7f0f9" if score > 0 else "#fdf0e6" if score < 0 else "#f3f4f6"
        return (f'<span style="color:{c};background:{bg};padding:2px 8px;'
                f'border-radius:4px;font-size:.8rem;font-weight:600;white-space:nowrap;">'
                f'{text}</span>')

    def f1(v):  # PMI 一位小數
        return f"{v:.1f}" if v == v else "—"

    def fi(v):  # NFP 整數帶號
        return f"{v:+.0f}" if v == v else "—"

    pmi = f1(mrow["pmi"]) if mrow is not None and pd.notna(mrow["pmi"]) else "—"
    nfp = fi(mrow["nfp"]) if mrow is not None and pd.notna(mrow["nfp"]) else "—"
    fdtr = f'{mrow["fdtr"]:.2f}%' if mrow is not None and pd.notna(mrow["fdtr"]) else "—"
    fed_cycle = {1: "降息循環", 0: "利率不變", -1: "升息循環"}[int(last["fed_score"])]

    def arrow(a, b):  # 近3月均 vs 近6月均 動能方向（用未四捨五入值比較）
        if a != a or b != b:
            return ""
        if a > b:
            return f' <span style="color:{C_UP}">▲</span>'
        if a < b:
            return f' <span style="color:{C_DOWN}">▼</span>'
        return ""

    # (因子, 最新, 近3月均, 近6月均, 分數, 解讀)
    rows = [
        ("綜合 PMI", pmi, f1(mas["pmi_3"]) + arrow(mas["pmi_3"], mas["pmi_6"]),
         f1(mas["pmi_6"]), int(last["pmi_score"]), read(last["pmi_score"])),
        ("非農就業 (千人)", nfp, fi(mas["nfp_3"]) + arrow(mas["nfp_3"], mas["nfp_6"]),
         fi(mas["nfp_6"]), int(last["nfp_score"]), read(last["nfp_score"])),
        ("Fed 利率上緣", fdtr, "—", "—",
         int(last["fed_score"]), f"{read(last['fed_score'])}・{fed_cycle}"),
    ]
    body = ""
    for name, latest, m3, m6, sc, rd in rows:
        body += (f'<tr><td>{name}</td><td class="num">{latest}</td>'
                 f'<td class="num">{m3}</td><td class="num">{m6}</td>'
                 f'<td class="ctr">{cell(sc)}</td><td>{badge(sc, rd)}</td></tr>')

    macro = int(last["macro_score"])
    dir_word = {1: "加碼", 0: "維持", -1: "減碼"}[int(last["direction"])]
    dir_col = C_UP if last["direction"] > 0 else C_DOWN if last["direction"] < 0 else C_FLAT
    return f"""
    <table class="scorecard">
      <thead><tr><th>因子</th><th class="num">最新</th><th class="num">近3月均</th>
        <th class="num">近6月均</th><th class="ctr">分數</th><th>解讀</th></tr></thead>
      <tbody>{body}</tbody>
      <tfoot><tr><td>總體合計</td><td class="num" colspan="3"></td>
        <td class="ctr"><b>{macro:+d}</b></td>
        <td><b style="color:{dir_col}">→ {dir_word}</b></td></tr></tfoot>
    </table>
    <ul class="sc-note">
      <li><span style="color:{C_UP}">▲</span><span style="color:{C_DOWN}">▼</span> PMI／NFP 動能：近3月均 vs 近6月均，近3月均較高＝動能向上（▲），反之為向下（▼）</li>
      <li>Fed 因子：依利率上緣變動方向判定，不適用動能均值比較</li>
    </ul>
    """


def _perf_table_html(results_list, name_list, rule):
    head = ("<tr><th>策略</th><th>總報酬</th><th>CAGR</th><th>Sharpe</th>"
            "<th>Sortino</th><th>MDD</th><th>Calmar</th></tr>")
    body = ""
    for name, res in zip(name_list, results_list):
        nav = res[rule]["nav"]
        s = res[rule]["stats"]
        tr = nav.iloc[-1] / nav.iloc[0] - 1
        hl = ' class="hl"' if name == "SAA + TAA" else ""
        body += (f"<tr{hl}><td>{STRAT_LABEL.get(name, name)}</td>"
                 f"<td>{tr:.1%}</td><td>{s.get('CAGR', float('nan')):.2%}</td>"
                 f"<td>{s.get('Sharpe', float('nan')):.2f}</td>"
                 f"<td>{s.get('Sortino', float('nan')):.2f}</td>"
                 f"<td>{s.get('max_drawdown', float('nan')):.1%}</td>"
                 f"<td>{s.get('Calmar', float('nan')):.2f}</td></tr>")
    return f'<table class="data"><thead>{head}</thead><tbody>{body}</tbody></table>'


def _weights_table_html(saa_latest, taa_latest):
    rows = []
    for asset in taa_latest.index:
        saa_w, taa_w = float(saa_latest.get(asset, 0)), float(taa_latest[asset])
        if abs(saa_w) < 1e-9 and abs(taa_w) < 1e-9:
            continue
        rows.append((ASSET_LABELS.get(asset, asset), saa_w, taa_w, taa_w - saa_w))
    rows.sort(key=lambda r: r[2], reverse=True)
    body = ""
    for name, saa_w, taa_w, d in rows:
        dc = C_UP if d > 1e-9 else C_DOWN if d < -1e-9 else C_FLAT
        ds = f'<span style="color:{dc}">{d:+.1%}</span>' if abs(d) > 1e-9 else "—"
        body += f"<tr><td>{name}</td><td>{saa_w:.1%}</td><td>{taa_w:.1%}</td><td>{ds}</td></tr>"
    return ('<table class="data"><thead><tr><th>資產</th><th>SAA</th>'
            f'<th>SAA+TAA</th><th>Δ</th></tr></thead><tbody>{body}</tbody></table>')


def _weights_detail_html(saa_latest, taa_latest):
    rows = []
    for asset in taa_latest.index:
        saa_w = float(saa_latest.get(asset, 0))
        taa_w = float(taa_latest[asset])
        if abs(saa_w) < 1e-9 and abs(taa_w) < 1e-9:
            continue
        cat  = _ASSET_CAT.get(asset, "資產")
        name = _ASSET_DISPLAY.get(asset, asset)
        rows.append((cat, name, saa_w, taa_w, taa_w - saa_w))

    rows.sort(key=lambda r: (_CAT_ORDER.get(r[0], 9), -r[2]))  # 分類排序，同類內依 SAA 降冪

    body = ""
    cur_cat = None
    for cat, name, saa_w, taa_w, delta in rows:
        if cat != cur_cat:
            body += f'<tr class="cat-hdr"><td colspan="4">{cat}</td></tr>'
            cur_cat = cat
        dc = C_UP if delta > 1e-9 else C_DOWN if delta < -1e-9 else C_FLAT
        ds = f'<span style="color:{dc};font-weight:600">{delta:+.1%}</span>' if abs(delta) > 1e-9 else "—"
        body += (f"<tr><td>{name}</td><td>{saa_w:.1%}</td>"
                 f"<td>{taa_w:.1%}</td><td>{ds}</td></tr>")

    head = ("<tr><th>地區／產業／資產</th><th>調整前 (SAA)</th>"
            "<th>調整後 (SAA+TAA)</th><th>調整幅度</th></tr>")
    return f'<table class="data wt"><thead>{head}</thead><tbody>{body}</tbody></table>'


def _fig_taa_signals(signals_df):
    vals = signals_df["delta_x"] * 100
    fig = go.Figure(go.Bar(
        x=signals_df.index, y=vals,
        marker_color=[C_UP if v > 0 else C_DOWN if v < 0 else C_FLAT for v in vals],
        hovertemplate="%{x|%Y-%m}<br>ΔX %{y:+.1f}%<extra></extra>",
    ))
    fig.update_layout(
        height=320,
        yaxis_title="ΔX (%)",
        showlegend=False,
        **_PLOT_LAYOUT,
    )
    return _fig_html(fig)


def _signals_history_html(signals_df, X, n=6):
    recent = signals_df.tail(n).iloc[::-1]

    def sc(v):
        iv = int(v)
        c  = C_UP if iv > 0 else C_DOWN if iv < 0 else "#9aa0a6"
        fw = "font-weight:600;" if iv != 0 else ""
        txt = f"{iv:+d}" if iv != 0 else "0"
        return f'<td class="num" style="color:{c};{fw}">{txt}</td>'

    head = ("<tr><th></th><th>PMI</th><th>NFP</th><th>Fed</th>"
            "<th>總體</th><th>方向</th><th>市場</th><th>評價</th>"
            "<th>乘數</th><th>ΔX</th><th>會議</th></tr>")
    body = ""
    for dt, row in recent.iterrows():
        dir_s = int(row["direction"])
        dx    = float(row["delta_x"])
        meet  = bool(row["meeting_flag"])
        mult  = abs(dx) / X if dir_s != 0 and X > 0 else 0.0

        dir_word = "加碼" if dir_s > 0 else "減碼" if dir_s < 0 else "維持"
        dir_col  = C_UP if dir_s > 0 else C_DOWN if dir_s < 0 else "#9aa0a6"
        mkt_word = ">10MA" if int(row["market_above_10MA"]) > 0 else "<10MA"
        dx_col   = C_UP if dx > 1e-9 else C_DOWN if dx < -1e-9 else "#9aa0a6"

        body += (
            f'<tr>'
            f'<td>{dt.strftime("%Y-%m")}</td>'
            f'{sc(row["pmi_score"])}{sc(row["nfp_score"])}{sc(row["fed_score"])}{sc(row["macro_score"])}'
            f'<td style="color:{dir_col};font-weight:600">{dir_word}</td>'
            f'<td>{mkt_word}</td>'
            f'{sc(row["erp_score"])}'
            f'<td class="num">{mult:.2f}</td>'
            f'<td class="num" style="color:{dx_col};font-weight:600">{dx*100:+.1f}%</td>'
            f'<td style="text-align:center">{"⚠" if meet else ""}</td>'
            f'</tr>'
        )
    return f'<table class="data"><thead>{head}</thead><tbody>{body}</tbody></table>'


def _params_html(cfg, X, rule, signals_df):
    m = cfg["taa"]["valuation_multipliers"]
    rule_map = {"M": "每月", "Q": "每季", "A": "每年", "2Q-DEC": "半年(6/12月)"}
    n_active = int((signals_df["delta_x"] != 0).sum())
    n_meeting = int(signals_df["meeting_flag"].sum())
    items = [
        ("股債比最大調整 X", f"{X:.1%}"),
        ("評價乘數（便宜/正常/昂貴）", f"{m['plus_1']:.2f} / {m['zero']:.2f} / {m['minus_1']:.2f}"),
        ("NFP 門檻", f"{cfg['taa'].get('nfp_threshold', 50):.0f} 千人"),
        ("PMI 榮枯線", f"{cfg['taa'].get('pmi_threshold', 50):.0f}"),
        ("再平衡頻率", rule_map.get(rule, rule)),
        ("交易成本", f"{cfg['backtest'].get('trading_cost_bps', 0):.0f} bps"),
        ("加碼規則", "債券等比例移出 → 全進 標普500 (SPX)"),
        ("減碼規則", "股票等比例移出 → 全進 投資級債 (LEGATRUU)"),
        ("回測期間有調整月份", f"{n_active} / {len(signals_df)} 個月"),
        ("觸及會議討論", f"{n_meeting} 個月"),
    ]
    lis = "".join(f"<li><span>{k}</span><b>{v}</b></li>" for k, v in items)
    return f'<ul class="params">{lis}</ul>'


# ============================================================
# AI Summary helpers
# ============================================================

def _build_summary_data(last, results_list, name_list, rule, cfg, profile, X,
                        saa_latest, taa_latest, commentary=None) -> dict:
    s_cols, b_cols = _buckets(cfg, saa_latest.index)
    saa_stock = float(saa_latest[s_cols].sum())
    taa_stock = float(taa_latest[s_cols].sum())
    perf = {name: res[rule]["stats"] for name, res in zip(name_list, results_list)}
    dt = last.name
    return {
        "profile": profile,
        "date": dt.strftime("%Y-%m") if hasattr(dt, "strftime") else str(dt),
        "direction": int(last["direction"]),
        "delta_x": float(last["delta_x"]),
        "macro_score": int(last["macro_score"]),
        "pmi_score": int(last["pmi_score"]),
        "nfp_score": int(last["nfp_score"]),
        "fed_score": int(last["fed_score"]),
        "market_above_10MA": bool(last["market_above_10MA"]),
        "erp_score": int(last["erp_score"]),
        "X": float(X),
        "saa_stock": saa_stock,
        "taa_stock": taa_stock,
        "stock_delta": taa_stock - saa_stock,
        "perf": perf,
        "commentary": commentary or {},
    }


def _build_summary_prompt(sd: dict) -> str:
    direction = sd["direction"]
    delta_x = sd["delta_x"]
    saa_s, taa_s = sd["saa_stock"], sd["taa_stock"]

    dir_word = "加碼" if direction > 0 else "減碼" if direction < 0 else "維持"
    erp_word = {
        1: "相對便宜（ERP > +1σ）", 0: "估值正常（ERP 在 ±1σ 區間）",
        -1: "相對昂貴（ERP < −1σ）",
    }.get(sd["erp_score"], "—")
    mkt_word = "高於" if sd["market_above_10MA"] else "低於"

    commentary = sd.get("commentary") or {}
    commentary_block = (
        "\n".join(f"【{topic}】{body}" for topic, body in commentary.items())
        if commentary else "（本期無月報文字，請僅依模型結論撰寫。）"
    )

    return (
        f"你是一位專業金融市場研究員。請整合「市場月報觀點」與「本期量化模型結論」，"
        f"以繁體中文撰寫一段專業金融市場分析，供{sd['profile']}閱讀。\n\n"
        f"寫作要求：\n"
        f"1. 須具備邏輯推演：原因 → 影響 → 市場結果。\n"
        f"2. 風格偏研究報告，語氣中性、專業。\n"
        f"3. 避免贅詞，句子精簡。\n"
        f"4. 字數嚴格控制在 120～150 字（中文字計）。\n"
        f"5. 結尾須包含市場影響結論，涵蓋匯率、股市走勢與『債市看法』；"
        f"債市部分須給出債券佈局觀點（例如偏好中短債或非投等債、存續期間取捨），"
        f"而非僅敘述利率水準。\n"
        f"6. 輸出單一段落，不要標題、項目符號、前言或後記。\n\n"
        f"【市場月報觀點】\n{commentary_block}\n\n"
        f"【本期量化模型結論（{sd['date']}）】\n"
        f"決策：{dir_word}股票，ΔX = {delta_x:+.1%}\n"
        f"總體三因子得分：{sd['macro_score']:+d}"
        f"（PMI {sd['pmi_score']:+d}、NFP {sd['nfp_score']:+d}、Fed {sd['fed_score']:+d}）\n"
        f"市場面：S&P 500 {mkt_word} 200 日均線\n"
        f"評價面：ERP {erp_word}\n"
        f"配置：股票 {saa_s:.1%} → {taa_s:.1%}（Δ {taa_s - saa_s:+.1%}）\n\n"
        + (
            f"【本次額外微調要求（最高優先，須遵守）】\n{extra}\n\n"
            if (extra := (sd.get("extra_instruction") or "").strip()) else ""
        )
        + "請直接輸出該段分析："
    )


def _wrap_paras(text: str) -> str:
    paras = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    if not paras:
        paras = [p.strip() for p in text.strip().split("\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paras)


def generate_summary_nlg(sd: dict) -> str:
    direction = sd["direction"]
    delta_x = sd["delta_x"]
    macro = sd["macro_score"]
    pmi, nfp, fed = sd["pmi_score"], sd["nfp_score"], sd["fed_score"]
    above = sd["market_above_10MA"]
    erp = sd["erp_score"]
    saa_s, taa_s = sd["saa_stock"], sd["taa_stock"]
    dx = sd["stock_delta"]
    taa_p = sd["perf"].get("SAA + TAA", {})
    saa_p = sd["perf"].get("Markowitz", {})

    if direction > 0:
        dir_txt = f"加碼股票 {abs(delta_x)*100:.1f}%"
        mac_txt = (f"總體面三因子合計得分 {macro:+d}（PMI {pmi:+d}、NFP {nfp:+d}、Fed {fed:+d}），"
                   f"景氣擴張訊號支持股票加碼。")
    elif direction < 0:
        dir_txt = f"減碼股票 {abs(delta_x)*100:.1f}%"
        mac_txt = (f"總體面三因子合計得分 {macro:+d}（PMI {pmi:+d}、NFP {nfp:+d}、Fed {fed:+d}），"
                   f"景氣收縮訊號支持股票減碼。")
    else:
        dir_txt = "維持 SAA 基準配置"
        mac_txt = (f"總體面三因子合計得分 {macro:+d}（PMI {pmi:+d}、NFP {nfp:+d}、Fed {fed:+d}），"
                   f"訊號中性，本期不執行戰術調整。")
    p1 = f"本期模型依據 {sd['date']} 月底資料，對{sd['profile']}建議{dir_txt}。{mac_txt}"

    mkt_txt = ("S&P 500 月底收盤高於 200 日均線，市場趨勢偏多，上升動能延續。"
               if above else
               "S&P 500 月底收盤低於 200 日均線，市場趨勢偏空，需留意下行風險。")
    erp_txt = {
        1:  "評價面 ERP 位於 +1σ 上方，股市相對債市偏低估，乘數放大執行幅度。",
        0:  "評價面 ERP 處於 ±1σ 正常區間，乘數維持中性。",
        -1: "評價面 ERP 位於 −1σ 下方，股市相對偏貴，乘數縮減加碼幅度。",
    }.get(erp, "")
    if abs(dx) > 1e-3:
        alloc_txt = (f"本期股票比例{'提升' if dx > 0 else '降低'}至 {taa_s:.1%}"
                     f"（SAA 基準為 {saa_s:.1%}）。")
    else:
        alloc_txt = f"本期不調整配置，股票比例維持 SAA 基準 {saa_s:.1%}。"
    p2 = f"{mkt_txt}{erp_txt}{alloc_txt}"

    taa_cagr = taa_p.get("CAGR", float("nan"))
    taa_sh   = taa_p.get("Sharpe", float("nan"))
    taa_mdd  = taa_p.get("max_drawdown", float("nan"))
    saa_cagr = saa_p.get("CAGR", float("nan"))
    saa_mdd  = saa_p.get("max_drawdown", float("nan"))
    if not math.isnan(taa_cagr) and not math.isnan(saa_cagr):
        perf_txt = (
            f"回測期間 TAA 策略年化報酬 {taa_cagr:.2%}（Sharpe {taa_sh:.2f}，"
            f"最大回撤 {taa_mdd:.1%}），{'優於' if taa_cagr >= saa_cagr else '略遜於'} SAA 基準"
            f"（CAGR {saa_cagr:.2%}、MDD {saa_mdd:.1%}）。"
        )
    else:
        perf_txt = ""
    note = ("建議結合定期人工判斷，尤其在市場面觸發「會議討論」旗標時，"
            "宜提交委員會評估後再執行。")
    p3 = f"{perf_txt}{note}"

    return f"<p>{p1}</p><p>{p2}</p><p>{p3}</p>"


def _fallback_nlg(sd: dict, reason: str) -> str:
    """退回規則式摘要，並把原因印到 stderr（避免靜默 fallback 害人誤判）。
    若有 --tweak（extra_instruction），額外警告該微調不會生效。"""
    import sys
    msg = f"⚠️  AI 摘要退回規則式（{reason}）。規則式摘要不採用月報文字。"
    if (sd.get("extra_instruction") or "").strip():
        msg += " 本次 --tweak 微調指令不會生效。"
    print(msg, file=sys.stderr)
    sd["_fell_back"] = True  # 供 build_html_report 修正來源標籤
    return generate_summary_nlg(sd)


def generate_summary_claude(sd: dict, model: str) -> str:
    try:
        import anthropic
    except ImportError:
        return _fallback_nlg(sd, "未安裝 anthropic 套件，請確認在專案 venv 執行")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return _fallback_nlg(sd, "找不到 ANTHROPIC_API_KEY，請確認 .env")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=700,
            messages=[{"role": "user", "content": _build_summary_prompt(sd)}],
        )
        return _wrap_paras(msg.content[0].text)
    except Exception as e:
        return _fallback_nlg(sd, f"Claude API 呼叫失敗：{e}")


def generate_summary_gemini(sd: dict) -> str:
    try:
        import google.generativeai as genai
    except ImportError:
        return _fallback_nlg(sd, "未安裝 google.generativeai 套件，請確認在專案 venv 執行")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return _fallback_nlg(sd, "找不到 GEMINI_API_KEY，請確認 .env")
    try:
        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel("gemini-2.5-flash")
        response = gemini_model.generate_content(_build_summary_prompt(sd))
        return _wrap_paras(response.text)
    except Exception as e:
        return _fallback_nlg(sd, f"Gemini API 呼叫失敗：{e}")


# ============================================================
# 主函式
# ============================================================

def build_html_report(run_data: dict, rule: str, ai_provider: str = "nlg",
                      summary_tweak: str | None = None,
                      summary_override: str | None = None) -> str:
    """summary_tweak：附加到 AI 摘要 prompt 的微調指令（自然語言）。
    summary_override：整段定稿全文，提供時直接取代摘要、跳過 LLM。
    兩者皆可改由環境變數提供（SUMMARY_TWEAK / SUMMARY_OVERRIDE /
    SUMMARY_OVERRIDE_FILE），方便用 CLI 快速下指令而不動 UI。"""
    results_list = run_data["results_list"]
    name_list = run_data["name_list"]
    cfg = run_data["cfg"]
    profile = run_data["profile"]
    taa = run_data["taa_info"]
    if taa is None:
        raise ValueError("報告需啟用 TAA（保守型或未啟用時無法產生）。")

    X = taa["X"]
    signals_df = taa["signals_df"]
    taa_data = taa["taa_data"]
    saa_latest = taa["saa_weights_df"].iloc[-1]
    taa_latest = taa["weights_df"].iloc[-1]

    D = signals_df.index[-1]
    obs = D - MonthEnd(1)
    last = signals_df.loc[D]
    mrow = _asof(taa_data["macro"], obs)

    # 近 3 / 6 月均值（與 compute_factor_scores 的 rolling 一致）
    _mac_obs = taa_data["macro"].loc[:obs]

    def _ma(col, n):
        s = _mac_obs[col].rolling(n).mean()
        return float(s.iloc[-1]) if len(s) else float("nan")
    mas = {
        "pmi_3": _ma("pmi", 3), "pmi_6": _ma("pmi", 6),
        "nfp_3": _ma("nfp", 3), "nfp_6": _ma("nfp", 6),
    }

    dx = float(last["delta_x"])
    if dx > 0:
        decision = f"建議加碼 {dx * 100:.1f}%"
        d_col = C_UP
    elif dx < 0:
        decision = f"建議減碼 {abs(dx) * 100:.1f}%"
        d_col = C_DOWN
    else:
        decision = "維持 SAA 配置"
        d_col = C_FLAT

    _mac = int(last["macro_score"])
    _mkt = int(last["market_above_10MA"])
    _erp = int(last["erp_score"])
    _mac_word = "偏強" if _mac > 0 else "偏弱" if _mac < 0 else "中性"
    _mkt_word = "偏多" if _mkt > 0 else "偏空"
    _erp_word = "相對便宜" if _erp > 0 else "相對昂貴" if _erp < 0 else "估值正常"
    _mac_col  = C_UP if _mac > 0 else C_DOWN if _mac < 0 else C_FLAT
    _mkt_col  = C_UP if _mkt > 0 else C_DOWN
    _erp_col  = C_UP if _erp > 0 else C_DOWN if _erp < 0 else C_FLAT
    sub = (
        f'<span style="color:{_mac_col};font-weight:600">總體面{_mac_word}</span>'
        f'<span style="color:#c8c5be;margin:0 14px">·</span>'
        f'<span style="color:{_mkt_col};font-weight:600">市場面{_mkt_word}</span>'
        f'<span style="color:#c8c5be;margin:0 14px">·</span>'
        f'<span style="color:{_erp_col};font-weight:600">評價面{_erp_word}</span>'
    )

    _direction = int(last["direction"])
    if _direction > 0:
        _macro_sub = f"PMI、NFP、Fed 三因子合計得分 {_mac:+d}，景氣擴張訊號支持加碼股票。"
    elif _direction < 0:
        _macro_sub = f"PMI、NFP、Fed 三因子合計得分 {_mac:+d}，景氣收縮訊號支持減碼股票。"
    else:
        _macro_sub = f"PMI、NFP、Fed 三因子合計得分 {_mac:+d}，訊號中性，本期維持 SAA 配置。"

    if _mkt > 0:
        _market_sub = "S&amp;P 500 收於 200 日均線上方，市場維持上升趨勢，動能尚未反轉。"
    else:
        _market_sub = "S&amp;P 500 跌破 200 日均線，市場趨勢偏空，留意下行風險。"

    # raw string 避免 \t \f 被 Python 當 escape sequence 吃掉
    _erp_formula = r"$$\text{ERP} = \dfrac{1}{\text{S\&P 500 Fwd P/E}} - \text{US 10Y YTM}$$"

    meeting_html = ""
    if bool(last["meeting_flag"]):
        meeting_html = ('<div class="meeting">⚠ 本期觸及「會議討論」範疇：總體面方向與市場面相左，'
                        '量化版預設仍跟隨原方向、不縮幅執行，實務上建議提交會議討論。</div>')

    bt_start_ts = pd.to_datetime(cfg["dates"]["backtest_start"])
    bt_start = bt_start_ts.strftime("%Y-%m")
    bt_end = pd.to_datetime(cfg["dates"]["backtest_end"]).strftime("%Y-%m")
    rule_map = {"M": "每月", "Q": "每季", "A": "每年", "2Q-DEC": "半年"}

    # 動態計算因子資料涵蓋（資料來源會被更新，避免寫死日期）
    def _first(s):
        s = s.dropna()
        return s.index.min() if len(s) else None
    pmi0 = _first(taa_data["macro"]["pmi"])
    nfp0 = _first(taa_data["macro"]["nfp"])
    erp0 = _first(taa_data["valuation"]["erp"])
    spx0 = _first(taa_data["market"]["spx"])
    starts = [d for d in (pmi0, nfp0, erp0, spx0) if d is not None]
    covers_full = bool(starts) and max(starts) <= bt_start_ts
    if covers_full:
        note_html = (
            "註：因子資料涵蓋——PMI／NFP 自 "
            f"{pmi0:%Y-%m}、ERP 自 {erp0:%Y-%m}、S&amp;P 500 自 {spx0:%Y-%m}，"
            f"皆早於回測起點（{bt_start}），故回測全期每月均有完整 TAA 訊號。"
            "Fed 因子採利率上緣（FDTR）變動方向判定。"
        )
    else:
        note_html = (
            "註：部分因子資料起始晚於回測起點，較早月份資料不足者該因子分數以 0 計（不調整）。"
            "Fed 因子採利率上緣（FDTR）變動方向判定。"
        )

    # 圖
    nav_html = _fig_nav(results_list, name_list, rule)
    market_html = _fig_market(taa_data["market"])
    erp_html = _fig_erp(taa_data["valuation"])
    donut_html = _fig_donut(saa_latest, taa_latest, cfg)

    # AI 摘要
    _ai_labels = {
        "nlg": "規則式摘要", "gemini": "Gemini 2.5 Flash",
        "sonnet": "Claude Sonnet 4.6", "opus": "Claude Opus 4.8",
    }
    _ai_label = _ai_labels.get(ai_provider, ai_provider)

    # 微調指令 / 整段覆寫（參數 > 環境變數；皆不顯示於 UI）
    _tweak = (summary_tweak if summary_tweak is not None
              else os.environ.get("SUMMARY_TWEAK", "")).strip()
    _override = (summary_override if summary_override is not None
                 else os.environ.get("SUMMARY_OVERRIDE", "")).strip()
    if not _override:
        _ovr_file = os.environ.get("SUMMARY_OVERRIDE_FILE", "")
        if _ovr_file and Path(_ovr_file).exists():
            _override = Path(_ovr_file).read_text(encoding="utf-8").strip()

    _commentary = taa_data.get("commentary")
    if not _commentary and taa_data.get("taa_path"):
        # 舊版快取（.last_run.pkl）可能未含 commentary，改由原始 Excel 補讀
        from engine.data_loader import load_monthly_commentary
        _commentary = load_monthly_commentary(taa_data["taa_path"])
    _sd = _build_summary_data(last, results_list, name_list, rule, cfg, profile,
                              X, saa_latest, taa_latest, commentary=_commentary)
    _sd["extra_instruction"] = _tweak

    if _override:
        _summary_body = _wrap_paras(_override)
        _ai_label = "人工修訂定稿"
    elif ai_provider == "gemini":
        _summary_body = generate_summary_gemini(_sd)
    elif ai_provider == "sonnet":
        _summary_body = generate_summary_claude(_sd, "claude-sonnet-4-6")
    elif ai_provider == "opus":
        _summary_body = generate_summary_claude(_sd, "claude-opus-4-8")
    else:
        _summary_body = generate_summary_nlg(_sd)
    if _sd.get("_fell_back"):  # LLM 不可用而自動退回 → 標籤誠實反映
        _ai_label = "規則式摘要（LLM 不可用，自動退回）"
    _ai_summary_html = (
        f'<div class="ai-summary">'
        f'<div class="ai-label">✦ AI 策略摘要</div>'
        f'<div class="ai-body">{_summary_body}</div>'
        f'<div class="ai-src">{_ai_label}</div>'
        f'</div>'
    )

    css = _CSS
    today = date.today().strftime("%Y-%m-%d")

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TAA 策略報告 — {profile}</title>
<script src="{PLOTLYJS_CDN}" charset="utf-8"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&family=Noto+Serif+TC:wght@600;700;900&display=swap" rel="stylesheet">
<style>{css}</style>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body,{{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'\\\\(',right:'\\\\)',display:false}}]}});"></script>
</head>
<body>
<nav class="tab-bar">
  <button class="tab active" onclick="showTab(0)">策略報告</button>
  <button class="tab" onclick="showTab(1)">模型參數與假設</button>
</nav>

<div class="page tab-panel active" id="tab-0">

  <header class="masthead">
    <div class="brand">MODEL PORTFOLIO LAB</div>
    <h1>戰術資產配置（TAA）策略報告</h1>
    <div class="meta">
      <span><i>投資人類型</i>{profile}</span>
      <span><i>再平衡</i>{rule_map.get(rule, rule)}</span>
      <span><i>回測區間</i>{bt_start} ～ {bt_end}</span>
      <span><i>產出日期</i>{today}</span>
    </div>
  </header>

  <section class="hero">
    <div class="hero-tag">當期決策（依 {obs.strftime('%Y-%m')} 月底資料 → {D.strftime('%Y-%m')} 配置）</div>
    <div class="hero-decision" style="color:{d_col}">{decision}</div>
    <div class="hero-sub">{sub}</div>
    {meeting_html}
    <hr class="hero-divider"/>
    {_ai_summary_html}
  </section>

  <div class="grid2">
    <section class="panel"><h2><span class="n">01</span>股債配置：調整前 vs 調整後</h2>{donut_html}</section>
    <section class="panel"><h2><span class="n">02</span>最新權重明細</h2>{_weights_detail_html(saa_latest, taa_latest)}</section>
  </div>

  <div class="grid2">
    <section class="panel"><h2><span class="n">03</span>總體面因子計分卡</h2><p class="panel-sub">{_macro_sub}</p>{_scorecard_html(last, mrow, mas)}</section>
    <section class="panel"><h2><span class="n">04</span>市場面因子：S&amp;P 500 與10月均線</h2><p class="panel-sub">{_market_sub}</p>{market_html}</section>
  </div>

  <section class="panel">
    <h2><span class="n">05</span>評價面因子：近五年股權風險溢價 (ERP) 平均及標準差位階</h2>
    {erp_html}
    <div class="erp-note">
      <div class="erp-formula">{_erp_formula}</div>
      <p>股權風險溢酬（Equity Risk Premium, ERP）：判斷股市的定價過高或過低（相對債市）。ERP 高 → 股市相對便宜，加碼乘數放大；ERP 低 → 股市相對昂貴，加碼乘數縮小。</p>
    </div>
  </section>

  <section class="panel">
    <h2><span class="n">06</span>回測績效：淨值曲線</h2>
    {nav_html}
    <p class="note bm-note">＊ 股六債四基準組成：60% MSCI 全球股票指數（MXWO）、20% 彭博全球投資級債指數（LEGATRUU）、20% 彭博美國30年期政府信用債指數（LG30TRUU），固定比例，不做再平衡。</p>
  </section>

  <hr class="rule"/>

  <section><h3>績效指標</h3>{_perf_table_html(results_list, name_list, rule)}</section>

  <footer class="disclaimer">本報告由 Model Portfolio Lab 自動生成，僅供內部研究與溝通參考，不構成投資建議。</footer>

</div>

<div class="page page-2 tab-panel" id="tab-1">

  <header class="masthead masthead-sm">
    <div class="brand">MODEL PORTFOLIO LAB</div>
    <div class="meta">
      <span><i>投資人類型</i>{profile}</span>
      <span><i>再平衡</i>{rule_map.get(rule, rule)}</span>
      <span><i>產出日期</i>{today}</span>
    </div>
  </header>

  <hr class="rule"/>
  <h2 class="detail-h">模型參數與假設</h2>

  <section>{_params_html(cfg, X, rule, signals_df)}</section>

  <section class="panel" style="margin-top:22px">
    <h2 style="font-family:'Noto Serif TC',serif;font-weight:700;font-size:1.12rem;margin:0 0 4px">TAA 訊號時序分析</h2>
    <p class="panel-sub">完整回測期間每月調整幅度紀錄</p>
    {_fig_taa_signals(signals_df)}
    <h3 style="margin:20px 0 8px">歷史訊號明細</h3>
    {_signals_history_html(signals_df, X)}
  </section>

  <p class="note">{note_html}</p>

  <footer class="disclaimer">本報告由 Model Portfolio Lab 自動生成，僅供內部研究與溝通參考，不構成投資建議。</footer>

</div>
<script>
function showTab(n) {{
  document.querySelectorAll('.tab-panel').forEach((p, i) => p.classList.toggle('active', i === n));
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', i === n));
}}
</script>
</body></html>"""


_CSS = r"""
:root { --ink:#1a1a1a; --muted:#6b7280; --accent:#0f4c5c; --paper:#fff; --line:#e3e1da; }
* { box-sizing:border-box; }
body { margin:0; background:#eceae4; color:var(--ink);
       font-family:"Noto Sans TC",sans-serif; line-height:1.55; }
.page { max-width:1080px; margin:24px auto; background:var(--paper);
        padding:44px 52px 36px; box-shadow:0 2px 18px rgba(0,0,0,.08); }

.masthead { border-bottom:3px solid var(--ink); padding-bottom:16px; margin-bottom:22px; }
.brand { font-size:.74rem; letter-spacing:.32em; color:var(--accent); font-weight:700; }
.masthead h1 { font-family:"Noto Serif TC",serif; font-weight:900;
               font-size:2.15rem; margin:.18em 0 .5em; letter-spacing:.01em; }
.meta { display:flex; flex-wrap:wrap; gap:26px; font-size:.86rem; color:var(--muted); }
.meta i { display:block; font-style:normal; font-size:.7rem; letter-spacing:.06em;
          color:#9aa0a6; margin-bottom:2px; }
.meta b, .meta span { color:var(--ink); }

.hero { background:#f7f5f0; border:1px solid var(--line); border-left:5px solid var(--accent);
        border-radius:8px; padding:22px 28px; margin-bottom:24px; }
.hero-top { display:flex; align-items:baseline; gap:28px; flex-wrap:wrap; }
.hero-tag { font-size:.78rem; color:var(--muted); letter-spacing:.03em; margin-bottom:6px; }
.hero-decision { font-family:"Noto Serif TC",serif; font-weight:900;
                 font-size:2.4rem; line-height:1.1; margin:.1em 0 .18em; }
.hero-sub { font-size:.96rem; color:#3a3a3a; }
.meeting { margin-top:12px; background:#fff7e6; border:1px solid #f0d690;
           color:#8a6d1f; padding:10px 14px; border-radius:6px; font-size:.9rem; }
.hero-divider { border:none; border-top:1px solid rgba(15,76,92,.15); margin:18px 0 16px; }
.ai-label { font-size:.72rem; letter-spacing:.12em; color:var(--accent);
            font-weight:700; text-transform:uppercase; margin-bottom:10px; }
.ai-body { font-size:.88rem; line-height:1.72; color:#2a2a2a;
           columns:2; column-gap:36px; }
.ai-body p { margin:0 0 9px; break-inside:avoid; }
.ai-body p:last-child { margin-bottom:0; }
.ai-src { font-size:.7rem; color:#b0b0b0; margin-top:12px; text-align:right; font-style:italic; }
@media(max-width:700px){
  .ai-body { columns:1; }
}

.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:22px; margin-bottom:22px; }
.panel { border:1px solid var(--line); border-radius:8px; padding:16px 18px 10px; background:#fff; }
.panel h2, .detail-h { font-family:"Noto Serif TC",serif; font-weight:700; font-size:1.12rem;
                       margin:0 0 4px; display:flex; align-items:center; gap:10px; }
.panel-sub { font-size:.82rem; color:var(--muted); margin:0 0 12px; }
.panel h2 .n { background:var(--accent); color:#fff; font-family:"Noto Sans TC";
               font-size:.72rem; font-weight:700; padding:3px 7px; border-radius:4px; letter-spacing:.05em; }

table { border-collapse:collapse; width:100%; font-size:.88rem; }
table th { text-align:left; color:var(--muted); font-weight:500; font-size:.78rem;
           border-bottom:1px solid var(--line); padding:7px 8px; }
table td { padding:7px 8px; border-bottom:1px solid #f1efe9; }
.scorecard .num, table .num { text-align:right; font-variant-numeric:tabular-nums; }
.scorecard .ctr { text-align:center; }
.scorecard .score { font-weight:700; font-size:1.02rem; }
.scorecard tfoot td { border-top:2px solid var(--ink); border-bottom:none;
                      font-weight:700; padding-top:9px; }
.scorecard th, .scorecard td { padding:9px 10px; font-size:.84rem; }
.scorecard tbody tr:nth-child(even) td { background:#f9f8f6; }
.sc-note { list-style:none; padding:0; margin:10px 2px 0; }
.sc-note li { font-size:.74rem; color:var(--muted); line-height:1.6; padding-left:1em; position:relative; }
.sc-note li::before { content:"·"; position:absolute; left:0; }
table.data td { font-variant-numeric:tabular-nums; }
table.data thead th:not(:first-child), table.data td:not(:first-child) { text-align:right; }
table.data tr.hl td { background:#fff8e1; }
table.data tr.cat-hdr td { background:#f0f4f8; color:var(--accent);
  font-weight:700; font-size:.78rem; letter-spacing:.06em;
  padding:6px 8px; border-bottom:1px solid var(--line); }

.rule { border:none; border-top:2px solid var(--ink); margin:30px 0 18px; }
.detail-h { font-size:1.4rem; }
h3 { font-family:"Noto Serif TC",serif; font-size:1.0rem; margin:0 0 10px; color:var(--accent); }

.params { list-style:none; padding:0; margin:0; columns:2; column-gap:34px; }
.params li { display:flex; justify-content:space-between; gap:12px; padding:6px 0;
             border-bottom:1px dotted var(--line); font-size:.88rem; break-inside:avoid; }
.params li span { color:var(--muted); }
.params li b { font-variant-numeric:tabular-nums; }

.note { font-size:.8rem; color:var(--muted); margin-top:18px; line-height:1.5; }
.bm-note { margin-top:8px; }
.erp-note { margin-top:10px; padding:10px 14px; background:#f7f5f0;
            border-radius:6px; border-left:3px solid var(--line); }
.erp-note p { font-size:.8rem; color:var(--muted); margin:6px 0 0; line-height:1.55; }
.erp-formula { text-align:center; font-size:.92rem; padding:4px 0; }
.disclaimer { margin-top:22px; padding-top:14px; border-top:1px solid var(--line);
              font-size:.76rem; color:#9aa0a6; text-align:center; }

.tab-bar { position:sticky; top:0; z-index:100; display:flex; gap:0;
           background:#fff; border-bottom:2px solid var(--ink);
           max-width:1080px; margin:0 auto; padding:0 52px; }
.tab { background:none; border:none; cursor:pointer; padding:10px 22px;
       font-family:"Noto Sans TC",sans-serif; font-size:.9rem; font-weight:500;
       color:var(--muted); border-bottom:3px solid transparent; margin-bottom:-2px;
       transition:color .15s, border-color .15s; }
.tab:hover { color:var(--ink); }
.tab.active { color:var(--accent); border-bottom-color:var(--accent); font-weight:700; }
.tab-panel { display:none; }
.tab-panel.active { display:block; }
.page-2 { margin-top:0; }
.masthead-sm { padding-bottom:10px; margin-bottom:14px; }
.masthead-sm h1 { display:none; }

@media print {
  body { background:#fff; }
  .page { box-shadow:none; margin:0; max-width:100%; padding:0 14px; }
  .page-2 { margin-top:0; page-break-before:always; }
  .panel, .hero { break-inside:avoid; }
}
"""
