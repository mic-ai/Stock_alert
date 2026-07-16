import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from indicators import calculate_rsi, calculate_ma, calculate_volume_ma, calculate_price_range


def make_close(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def make_ohlcv(n: int) -> pd.DataFrame:
    close = [100.0 + i for i in range(n)]
    return pd.DataFrame({
        "Open": close,
        "High": [v + 2 for v in close],
        "Low": [v - 2 for v in close],
        "Close": close,
        "Volume": [1000.0] * n,
    })


class TestCalculateMa:
    def test_short_series_has_nan_prefix(self):
        s = make_close(list(range(1, 11)))
        ma = calculate_ma(s, 5)
        assert pd.isna(ma.iloc[0])
        assert not pd.isna(ma.iloc[-1])

    def test_ma_value(self):
        s = make_close([1.0, 2.0, 3.0, 4.0, 5.0])
        ma = calculate_ma(s, 3)
        assert ma.iloc[-1] == pytest.approx(4.0)


class TestCalculateVolumeMa:
    def test_volume_ma(self):
        vol = pd.Series([100.0, 200.0, 300.0])
        ma = calculate_volume_ma(vol, 3)
        assert ma.iloc[-1] == pytest.approx(200.0)


class TestCalculatePriceRange:
    def test_range(self):
        df = make_ohlcv(5)
        rng = calculate_price_range(df)
        assert (rng == 4.0).all()


class TestCalculateRsi:
    def test_rsi_returns_series(self):
        close = make_close([float(i) for i in range(1, 30)])
        rsi = calculate_rsi(close, 14)
        assert rsi is not None
        assert isinstance(rsi, pd.Series)
        assert not rsi.dropna().empty

    def test_rsi_range(self):
        close = make_close([float(i) for i in range(1, 50)])
        rsi = calculate_rsi(close, 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()
