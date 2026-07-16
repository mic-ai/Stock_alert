import pandas as pd
import pandas_ta as ta


def calculate_rsi(close: pd.Series, length: int) -> pd.Series:
    return ta.rsi(close, length=length)


def calculate_ma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def calculate_volume_ma(volume: pd.Series, window: int) -> pd.Series:
    return volume.rolling(window).mean()


def calculate_price_range(df: pd.DataFrame) -> pd.Series:
    """日中値幅（High - Low）"""
    return df["High"] - df["Low"]
