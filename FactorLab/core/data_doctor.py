# -*- coding: utf-8 -*-
"""Data Doctor (clean version): turn raw market data into a clean long panel.

Output columns: date | code | open | high | low | close | volume | amount | vwap | returns

What it does, in order:
  1. load csv / parquet / xlsx
  2. auto-detect column mapping (Chinese + English aliases); caller may override
  3. basic cleaning: bad date/code dropped, duplicates removed, prices<=0 -> NaN,
     negative volume/amount -> NaN, inf -> NaN
  4. EXTREME-VALUE CLEANING: using CALENDAR-ALIGNED forward returns, drop rows
     whose `hold`-day forward return is impossible (> +100% or < -90%). Repeated
     a few rounds since deleting rows can expose new bad pairs. This is what
     removes the suspension-gap fakes that crater the backtest.
  5. compute vwap (amount/volume, else OHLC/4) and returns; save parquet.

No HTML report, no CLI prompt, no cache — just a clean panel + a short summary
dict. Cleaning is deterministic Python; AI is not involved here.
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd
from core.panel_utils import add_date_index, forward_return

COLUMN_CANDIDATES = {
    "date": ["date", "trade_date", "tradedate", "datetime", "time", "交易日期", "日期"],
    "code": ["code", "ticker", "symbol", "stock_code", "ts_code", "证券代码", "股票代码", "代码"],
    "open": ["open", "open_price", "openprice", "开盘", "开盘价"],
    "high": ["high", "high_price", "highprice", "最高", "最高价"],
    "low": ["low", "low_price", "lowprice", "最低", "最低价"],
    "close": ["close", "close_price", "closeprice", "adj_close", "收盘", "收盘价"],
    "volume": ["volume", "vol", "成交量"],
    "amount": ["amount", "turnover", "money", "成交额"],
    "vwap": ["vwap", "均价"],
    "returns": ["returns", "return", "ret", "收益率"],
}
REQUIRED = ["date", "code", "close"]
PRICE_COLS = ["open", "high", "low", "close"]
STD_ORDER = ["date", "code", "open", "high", "low", "close", "volume", "amount", "vwap", "returns"]

# extreme single-period forward-return thresholds (the "standard" level)
EXTREME_UP = 1.0     # > +100% in `hold` days -> corrupted
EXTREME_DOWN = -0.9  # < -90% in `hold` days  -> corrupted


def _norm(name):
    return str(name).strip().lower().replace(" ", "").replace("_", "")


def detect_column_mapping(df):
    """standard -> raw."""
    lookup = {_norm(c): c for c in df.columns}
    mapping = {}
    for std, cands in COLUMN_CANDIDATES.items():
        for c in cands:
            if _norm(c) in lookup:
                mapping[std] = lookup[_norm(c)]
                break
    return mapping


def suggest_mapping(df):
    """raw -> standard (kept for older GUI code)."""
    return {raw: std for std, raw in detect_column_mapping(df).items()}


def load_raw_data(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
    suf = path.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(path)
    if suf in (".parquet", ".pq"):
        return pd.read_parquet(path)
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise ValueError(f"Unsupported data format: {suf}")


load_raw = load_raw_data


def standardize_data(input_path, *, output_path="data/clean_panel.parquet",
                     column_mapping=None, hold_days_check=5,
                     extreme_up=EXTREME_UP, extreme_down=EXTREME_DOWN,
                     report_path=None, log_path=None,
                     drop_invalid_price_rows=False):
    """Return (clean_df, summary_dict). report_path/log_path accepted but unused
    (kept so older GUI calls don't break)."""
    raw = load_raw_data(input_path)
    summary = {"input": str(input_path), "raw_rows": int(len(raw))}

    mapping = detect_column_mapping(raw)
    if column_mapping:
        mapping.update(column_mapping)
    summary["column_mapping"] = mapping

    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        raise ValueError(f"Missing required columns after mapping: {missing}")

    df = pd.DataFrame({std: raw[rawc] for std, rawc in mapping.items() if rawc in raw.columns})

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["code"] = df["code"].astype(str).str.strip()
    bad = df["date"].isna() | (df["code"] == "") | (df["code"].str.lower() == "nan")
    df = df.loc[~bad].copy()
    summary["dropped_bad_date_code"] = int(bad.sum())

    n0 = len(df)
    df = df.drop_duplicates(subset=["date", "code"], keep="last")
    summary["duplicates_removed"] = int(n0 - len(df))

    for c in [x for x in ["open", "high", "low", "close", "volume", "amount", "vwap", "returns"] if x in df.columns]:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    for c in [x for x in PRICE_COLS if x in df.columns]:
        df[c] = df[c].where(df[c] > 0)
    if "volume" in df.columns:
        df["volume"] = df["volume"].where(df["volume"] >= 0)
    if "amount" in df.columns:
        df["amount"] = df["amount"].where(df["amount"] >= 0)

    if drop_invalid_price_rows:
        n1 = len(df); df = df.dropna(subset=["close"]).copy()
        summary["dropped_invalid_close"] = int(n1 - len(df))

    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    # ---- extreme-value cleaning via CALENDAR-ALIGNED forward returns ---- #
    removed_by_round = []
    for _ in range(5):
        d = add_date_index(df)
        fwd = forward_return(d, hold_days_check)
        mask = ((fwd > extreme_up) | (fwd < extreme_down)).fillna(False).values
        n_bad = int(mask.sum())
        removed_by_round.append(n_bad)
        if n_bad == 0:
            break
        df = df.loc[~mask].sort_values(["code", "date"]).reset_index(drop=True)
    summary["extreme_rows_removed"] = int(sum(removed_by_round))
    summary["extreme_removed_by_round"] = removed_by_round

    # vwap + returns
    if "vwap" not in df.columns:
        if "amount" in df.columns and "volume" in df.columns:
            df["vwap"] = (df["amount"] / df["volume"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        elif all(c in df.columns for c in PRICE_COLS):
            df["vwap"] = df[PRICE_COLS].mean(axis=1)
    cl = df["close"].where(df["close"] > 0)
    df["returns"] = cl.groupby(df["code"]).pct_change().replace([np.inf, -np.inf], np.nan)

    df = df[[c for c in STD_ORDER if c in df.columns]]

    summary.update({
        "final_rows": int(len(df)), "n_codes": int(df["code"].nunique()),
        "date_start": str(df["date"].min().date()) if len(df) else None,
        "date_end": str(df["date"].max().date()) if len(df) else None,
    })

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        summary["output"] = str(output_path)
    return df, summary


def print_summary(s):
    print("--- Data Doctor summary ---")
    print(f"raw rows: {s['raw_rows']}  ->  final rows: {s['final_rows']}")
    print(f"codes: {s['n_codes']}  period: {s.get('date_start')} -> {s.get('date_end')}")
    print(f"dropped bad date/code: {s.get('dropped_bad_date_code')}, "
          f"duplicates: {s.get('duplicates_removed')}")
    print(f"extreme rows removed: {s['extreme_rows_removed']} "
          f"(by round: {s['extreme_removed_by_round']})")
    if s.get("output"):
        print(f"clean panel saved: {s['output']}")
