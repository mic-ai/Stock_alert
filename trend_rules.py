import pandas as pd
from indicators import calculate_ma


def judge_trend(
    price_series: pd.Series,
    short: int,
    long: int,
    momentum_threshold: float,
    momentum_period: int,
) -> str:
    """要件定義書5-1に準拠したトレンド判定。

    Returns:
        "上昇トレンド" | "下降トレンド" | "レンジ" | "データ不足"
    """
    if len(price_series) < long:
        return "データ不足"
    ma_short = calculate_ma(price_series, short).iloc[-1]
    ma_long = calculate_ma(price_series, long).iloc[-1]
    momentum = price_series.iloc[-1] / price_series.iloc[-(momentum_period + 1)] - 1
    if ma_short > ma_long and momentum > momentum_threshold:
        return "上昇トレンド"
    elif ma_short < ma_long and momentum < -momentum_threshold:
        return "下降トレンド"
    return "レンジ"
