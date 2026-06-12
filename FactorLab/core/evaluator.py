# -*- coding: utf-8 -*-
"""Simple, robust factor evaluation.

- Forward return aligns by the real trading calendar (no cross-suspension fakes).
- Single-period returns are clipped to a sane band as a final safeguard.
- The long-short portfolio is rebalanced on NON-OVERLAPPING dates (every `hold`
  trading days) so the NAV is not inflated by counting a return `hold` times.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy import stats
from core.panel_utils import add_date_index, forward_return

MIN_STOCKS = 5
CLIP = 1.0  # clip single-period returns to +/-100% as a last-resort safeguard


def evaluate(df: pd.DataFrame, factor: pd.Series, hold_days: int = 5,
             n_groups: int = 5) -> dict:
    d = add_date_index(df[["date", "code", "close"]].copy())
    d["factor"] = np.asarray(factor, dtype="float64")
    d["fwd_ret"] = forward_return(d, hold_days).values
    d["fwd_ret"] = d["fwd_ret"].clip(-CLIP, CLIP)
    d["date"] = pd.to_datetime(d["date"])

    coverage = float(d["factor"].notna().mean())
    fmean = float(d["factor"].mean(skipna=True))
    fstd = float(d["factor"].std(skipna=True))

    valid = d.dropna(subset=["factor", "fwd_ret"])
    valid = valid[np.isfinite(valid["factor"]) & np.isfinite(valid["fwd_ret"])]

    ic_rows = []
    for date, g in valid.groupby("date"):
        if len(g) < MIN_STOCKS or g["factor"].std() == 0 or g["fwd_ret"].std() == 0:
            continue
        ic = stats.pearsonr(g["factor"], g["fwd_ret"])[0]
        ric = stats.spearmanr(g["factor"], g["fwd_ret"])[0]
        ic_rows.append((date, ic, ric))
    ic_df = pd.DataFrame(ic_rows, columns=["date", "ic", "rank_ic"]).set_index("date")

    def _stat(s):
        s = s.dropna(); m, sd, n = s.mean(), s.std(ddof=1), len(s)
        ir = m / sd if sd else np.nan
        t = ir * np.sqrt(n) if n and sd else np.nan
        return {"mean": float(m) if n else np.nan, "std": float(sd) if n else np.nan,
                "ir": float(ir) if n else np.nan, "t_stat": float(t) if n else np.nan,
                "win_rate": float((s > 0).mean()) if n else np.nan, "n": int(n)}

    ic_stats = _stat(ic_df["ic"]) if len(ic_df) else _stat(pd.Series(dtype=float))
    ric_stats = _stat(ic_df["rank_ic"]) if len(ic_df) else _stat(pd.Series(dtype=float))

    all_dates = np.sort(valid["date"].unique())
    rebal = set(all_dates[::hold_days])
    pv = valid[valid["date"].isin(rebal)]
    group_means, ls_series = _groups(pv, n_groups)
    ls_curve = (1.0 + ls_series).cumprod() if len(ls_series) else pd.Series(dtype=float)
    max_dd = _max_drawdown(ls_curve) if len(ls_curve) else np.nan
    ls_total = float(ls_curve.iloc[-1] - 1.0) if len(ls_curve) else np.nan

    return {
        "hold_days": hold_days, "n_rows": int(len(df)),
        "n_codes": int(df["code"].nunique()),
        "date_start": str(pd.to_datetime(df["date"]).min().date()),
        "date_end": str(pd.to_datetime(df["date"]).max().date()),
        "coverage": coverage, "factor_mean": fmean, "factor_std": fstd,
        "ic": ic_stats, "rank_ic": ric_stats, "ic_series": ic_df,
        "group_means": group_means, "ls_series": ls_series, "ls_curve": ls_curve,
        "ls_total_return": ls_total,
        "max_drawdown": float(max_dd) if max_dd == max_dd else np.nan,
        "monotonic": _is_monotonic(group_means), "evidence": _evidence(ic_stats),
    }


def _groups(valid, n_groups):
    rows, ls = {}, {}
    for date, g in valid.groupby("date"):
        if len(g) < max(MIN_STOCKS, n_groups):
            continue
        try:
            q = pd.qcut(g["factor"].rank(method="first"), n_groups,
                        labels=False, duplicates="drop")
        except ValueError:
            continue
        gg = g.assign(q=q); m = gg.groupby("q")["fwd_ret"].mean()
        rows[date] = {int(k): v for k, v in m.items()}
        if 0 in m.index and (n_groups - 1) in m.index:
            ls[date] = m[n_groups - 1] - m[0]
    per = pd.DataFrame(rows).T
    group_means = per.mean().reindex(range(n_groups))
    group_means.index = [f"Q{i+1}" for i in group_means.index]
    return group_means, pd.Series(ls).sort_index()


def _max_drawdown(curve):
    return float((curve / curve.cummax() - 1.0).min())


def _is_monotonic(group_means):
    v = group_means.dropna().values
    if len(v) < 3:
        return "n/a"
    if np.all(np.diff(v) > 0):
        return "increasing"
    if np.all(np.diff(v) < 0):
        return "decreasing"
    return "non-monotonic"


def _evidence(ic):
    t = abs(ic["t_stat"]) if ic["t_stat"] == ic["t_stat"] else 0
    return "Strong" if t >= 2 else ("Medium" if t >= 1 else "Weak")
