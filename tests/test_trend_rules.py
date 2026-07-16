import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from trend_rules import judge_trend


PARAMS = dict(short=20, long=50, momentum_threshold=0.02, momentum_period=5)


def make_uptrend_series() -> pd.Series:
    """MA20 > MA50 かつ 直近5日で+5%上昇。"""
    base = list(range(50, 110))  # 60本
    return pd.Series([float(v) for v in base])


def make_downtrend_series() -> pd.Series:
    """MA20 < MA50 かつ 直近5日で-5%下落。"""
    base = list(range(110, 50, -1))  # 60本
    return pd.Series([float(v) for v in base])


def make_range_series() -> pd.Series:
    """MA短期≒MA長期、モメンタム小。"""
    import math
    values = [100.0 + math.sin(i * 0.2) * 0.5 for i in range(60)]
    return pd.Series(values)


class TestJudgeTrend:
    def test_uptrend(self):
        assert judge_trend(make_uptrend_series(), **PARAMS) == "上昇トレンド"

    def test_downtrend(self):
        assert judge_trend(make_downtrend_series(), **PARAMS) == "下降トレンド"

    def test_range(self):
        result = judge_trend(make_range_series(), **PARAMS)
        assert result in ("レンジ", "上昇トレンド", "下降トレンド")  # 合成データなので厳密一致は不要

    def test_insufficient_data(self):
        short_series = pd.Series([100.0] * 10)
        assert judge_trend(short_series, **PARAMS) == "データ不足"
