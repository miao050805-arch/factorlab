# -*- coding: utf-8 -*-
"""Generate a clean, Apple-report-style self-contained HTML report with four
charts embedded as base64 PNGs. Optional PDF export if a backend is available.
"""
from __future__ import annotations
import os
import io
import base64
import datetime as dt
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK = "#1d1d1f"; SUB = "#86868b"; BLUE = "#0071e3"
GREEN = "#34c759"; RED = "#ff3b30"; GRID = "#e8e8ed"


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _style(ax, title):
    ax.set_title(title, fontsize=12, color=INK, pad=10, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=SUB, labelsize=8)
    ax.grid(axis="y", color=GRID, lw=.7)
    ax.set_axisbelow(True)


def _charts(ev) -> dict:
    out = {}
    ic = ev["ic_series"]

    fig, ax = plt.subplots(figsize=(6, 2.6))
    if len(ic):
        cols = [GREEN if v >= 0 else RED for v in ic["ic"]]
        ax.bar(range(len(ic)), ic["ic"], color=cols, width=1.0)
        ax.axhline(ic["ic"].mean(), color=INK, ls="--", lw=1)
    _style(ax, f"IC time series   (mean {ev['ic']['mean']:.3f})")
    out["ic"] = _fig_to_b64(fig)

    fig, ax = plt.subplots(figsize=(6, 2.6))
    if len(ic):
        cols = [GREEN if v >= 0 else RED for v in ic["rank_ic"]]
        ax.bar(range(len(ic)), ic["rank_ic"], color=cols, width=1.0)
        ax.axhline(ic["rank_ic"].mean(), color=INK, ls="--", lw=1)
    _style(ax, f"RankIC time series   (mean {ev['rank_ic']['mean']:.3f})")
    out["rank_ic"] = _fig_to_b64(fig)

    fig, ax = plt.subplots(figsize=(6, 2.6))
    c = ev["ls_curve"]
    if len(c):
        ax.plot(range(len(c)), c.values, color=BLUE, lw=1.6)
        ax.axhline(1.0, color=GRID, lw=1)
    _style(ax, "Long-short cumulative return (Q5 - Q1)")
    out["ls"] = _fig_to_b64(fig)

    fig, ax = plt.subplots(figsize=(6, 2.6))
    gm = ev["group_means"].dropna()
    if len(gm):
        colors = plt.cm.RdYlGn(np.linspace(0, 1, len(gm)))
        ax.bar(gm.index, gm.values, color=colors)
    _style(ax, "Quantile group average forward return")
    out["groups"] = _fig_to_b64(fig)
    return out


def _card(label, value, accent=INK):
    return f'<div class="card"><div class="k">{label}</div>' \
           f'<div class="v" style="color:{accent}">{value}</div></div>'


def _fmt(x, pct=False):
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"{x*100:.2f}%" if pct else f"{x:.3f}"


def generate(ev: dict, tr: dict, factor_name: str, code: str,
             static_status: str, out_dir: str) -> str:
    charts = _charts(ev)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    ev_color = {"Strong": GREEN, "Medium": "#ff9f0a", "Weak": SUB}[ev["evidence"]]

    cards = "".join([
        _card("Coverage", _fmt(ev["coverage"], pct=True)),
        _card("IC mean", _fmt(ev["ic"]["mean"]), GREEN if ev["ic"]["mean"] and ev["ic"]["mean"] > 0 else RED),
        _card("RankIC mean", _fmt(ev["rank_ic"]["mean"])),
        _card("ICIR", _fmt(ev["ic"]["ir"])),
        _card("RankICIR", _fmt(ev["rank_ic"]["ir"])),
        _card("IC t-stat", _fmt(ev["ic"]["t_stat"]), ev_color),
        _card("Long-short return", _fmt(ev["ls_total_return"], pct=True)),
        _card("Max drawdown", _fmt(ev["max_drawdown"], pct=True), RED),
        _card("Evidence", ev["evidence"], ev_color),
    ])

    helpers = ", ".join(tr.get("helpers_used", "").split()) if isinstance(tr.get("helpers_used"), str) else ""
    logic = tr.get("factor_logic", "(not available)")
    decomp = tr.get("decomposition", "")
    fields = tr.get("required_fields", "")
    notes = tr.get("translation_notes", "")

    interp = _interpret(ev)

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Factor Report — {factor_name}</title>
<style>
 body{{font:15px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",
   "PingFang SC",sans-serif;color:{INK};background:#fff;margin:0}}
 .wrap{{max-width:920px;margin:0 auto;padding:54px 40px 80px}}
 h1{{font-size:34px;letter-spacing:-.02em;margin:0 0 6px}}
 .sub{{color:{SUB};font-size:14px}}
 .meta{{display:flex;flex-wrap:wrap;gap:18px;margin:18px 0 30px;color:{SUB};font-size:13px}}
 .meta b{{color:{INK};font-weight:600}}
 h2{{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:{SUB};
   margin:40px 0 14px;font-weight:600}}
 .cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
 .card{{border:1px solid {GRID};border-radius:14px;padding:16px 18px}}
 .card .k{{font-size:12px;color:{SUB}}} .card .v{{font-size:22px;font-weight:600;margin-top:4px}}
 .charts{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
 .charts img{{width:100%;border:1px solid {GRID};border-radius:14px}}
 pre{{background:#f5f5f7;border:1px solid {GRID};border-radius:12px;padding:16px;
   overflow:auto;font:13px/1.5 "SF Mono",ui-monospace,Menlo,Consolas,monospace}}
 .kv{{font-size:14px}} .kv div{{margin:4px 0}} .kv b{{color:{SUB};font-weight:500}}
 .interp{{background:#f5f5f7;border-radius:14px;padding:20px 22px;font-size:14.5px}}
 .pill{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:12px;
   color:#fff;background:{ev_color}}}
 .foot{{margin-top:40px;color:{SUB};font-size:12px}}
</style></head><body><div class="wrap">
 <h1>AI Factor Reproduction Report</h1>
 <div class="sub">Factor <b style="color:{INK}">{factor_name}</b> · <span class="pill">{ev['evidence']} evidence</span></div>
 <div class="meta">
   <div>Generated <b>{now}</b></div>
   <div>Period <b>{ev['date_start']} → {ev['date_end']}</b></div>
   <div>Stocks <b>{ev['n_codes']}</b></div>
   <div>Holding <b>{ev['hold_days']} days</b></div>
   <div>Static check <b>{static_status}</b></div>
 </div>

 <h2>Key metrics</h2>
 <div class="cards">{cards}</div>

 <h2>Charts</h2>
 <div class="charts">
   <img src="data:image/png;base64,{charts['ic']}">
   <img src="data:image/png;base64,{charts['rank_ic']}">
   <img src="data:image/png;base64,{charts['ls']}">
   <img src="data:image/png;base64,{charts['groups']}">
 </div>

 <h2>Interpretation</h2>
 <div class="interp">{interp}</div>

 <h2>Translation summary</h2>
 <div class="kv">
   <div><b>Required fields:</b> {fields or '—'}</div>
   <div><b>Helpers used:</b> {tr.get('helpers_used','—') or '—'}</div>
   <div><b>Logic:</b> {logic}</div>
 </div>
 {f'<h2>Decomposition</h2><pre>{decomp}</pre>' if decomp else ''}
 {f'<h2>Translation notes</h2><div class="kv">{notes}</div>' if notes else ''}

 <h2>Translated code</h2>
 <pre>{_esc(code)}</pre>

 <div class="foot">This is a reproduction-and-evaluation demo, not investment
   advice and not production validation. Metrics are computed on the provided
   data with a simple, overlapping-window backtest.</div>
</div></body></html>"""

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"report_{factor_name}.html")
    open(path, "w", encoding="utf-8").write(html)
    return path


def _interpret(ev):
    ic, t = ev["ic"]["mean"], ev["ic"]["t_stat"]
    direction = "positive" if (ic == ic and ic > 0) else ("negative" if ic == ic else "unclear")
    parts = []
    if ic == ic:
        parts.append(f"The factor shows a <b>{direction}</b> average IC of "
                     f"{ic:.3f} (t-stat {t:.2f}, {ev['ic']['n']} cross-sections).")
    parts.append(f"Evidence level is <b>{ev['evidence']}</b> by the |t-stat| rule.")
    parts.append(f"Quantile group returns are <b>{ev['monotonic']}</b>.")
    if ev["evidence"] == "Weak":
        parts.append("The current sample does not support a confident conclusion "
                     "about predictive power.")
    return " ".join(parts)


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_pdf(html_path: str) -> str | None:
    """Best-effort PDF export. Returns path or None if no backend available."""
    pdf_path = html_path.replace(".html", ".pdf")
    try:
        from weasyprint import HTML
        HTML(html_path).write_pdf(pdf_path)
        return pdf_path
    except Exception:
        return None
