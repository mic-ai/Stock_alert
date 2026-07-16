import pandas as pd


def calculate_rsi(close: pd.Series, length: int) -> pd.Series:
    """Wilderの平滑化法によるRSI計算（pandas-ta不要）。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_ma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def calculate_volume_ma(volume: pd.Series, window: int) -> pd.Series:
    return volume.rolling(window).mean()


def calculate_price_range(df: pd.DataFrame) -> pd.Series:
    """日中値幅（High - Low）"""
    return df["High"] - df["Low"]
