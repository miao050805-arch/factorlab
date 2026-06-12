# -*- coding: utf-8 -*-
"""Shared panel helpers. The key one is a forward return that aligns by the
real TRADING CALENDAR: the return at date t uses the close exactly `hold`
trading days later FOR THE SAME STOCK, and only if that stock actually has
data on that day. Pairs that would span a suspension gap become NaN instead
of producing fake 100%+ jumps. Fully vectorized (merge on date-index)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def add_date_index(df: pd.DataFrame) -> pd.DataFrame:
    """Add integer 'di' = position of each date in the global sorted calendar."""
    all_dates = pd.Index(sorted(pd.to_datetime(df["date"]).unique()))
    pos = {d: i for i, d in enumerate(all_dates)}
    out = df.copy()
    out["di"] = pd.to_datetime(out["date"]).map(pos).astype("int64")
    return out


def forward_return(df: pd.DataFrame, hold: int, price_col: str = "close") -> pd.Series:
    """Calendar-aligned forward return: close[code, di+hold]/close[code, di]-1.
    Returns a Series aligned to df.index; cross-suspension pairs are NaN."""
    d = df if "di" in df.columns else add_date_index(df)
    base = d[["code", "di", price_col]].copy()
    base = base.rename(columns={price_col: "_p_t"})
    look = d[["code", "di", price_col]].copy()
    look = look.rename(columns={price_col: "_p_fut", "di": "_di_src"})
    base["_di_tgt"] = base["di"] + hold
    merged = base.merge(
        look, left_on=["code", "_di_tgt"], right_on=["code", "_di_src"], how="left")
    fwd = merged["_p_fut"].values / merged["_p_t"].values - 1.0
    s = pd.Series(fwd, index=d.index)
    return s.replace([np.inf, -np.inf], np.nan)
