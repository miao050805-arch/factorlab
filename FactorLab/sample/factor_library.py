# Example external factor library that depends on operators.py
def _alpha4(df):
    rank_low = cross_sectional_rank(df, "low")
    ts_rank_low = ts_rank(df.assign(rank_low=rank_low), "rank_low", 9, min_periods=9)
    return -ts_rank_low

def _alpha6(df):
    return -1 * ts_corr(df, "open", "volume", 10)

def _alpha_delta(df):
    return ts_delta(df, "close", 1)

def load_prices(path):  # should be classified as data/helper, not a factor
    import pandas as pd
    return pd.read_parquet(path)
