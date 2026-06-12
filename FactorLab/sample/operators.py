# Example operator/helper library (long-format, group by code/date)
import numpy as np
import pandas as pd

def cross_sectional_rank(df, col):
    return df.groupby("date")[col].rank(pct=True)

def ts_rank(df, col, window, min_periods=None):
    mp = min_periods or window
    def _r(s):
        return s.rolling(window, min_periods=mp).apply(
            lambda w: (np.sum(w <= w[-1]) - 1) / (len(w) - 1) if len(w) > 1 else np.nan, raw=True)
    return df.groupby("code")[col].transform(_r)

def ts_delta(df, col, n):
    return df.groupby("code")[col].diff(n)

def ts_corr(df, a, b, window):
    return df.groupby("code", group_keys=False).apply(
        lambda g: g[a].rolling(window).corr(g[b]))

def safe_div(a, b):
    return a / b.replace(0, np.nan)
