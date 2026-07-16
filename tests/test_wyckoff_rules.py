import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from wyckoff_rules import (
    detect_sc,
    detect_ar,
    detect_spring,
    detect_choch,
    check_wyckoff_buy_pattern,
    check_wyckoff_sell_pattern,
)

CFG = {
    "wyckoff": {
        "lookback": 20,
        "sc": {"volume_ratio": 2.0, "range_ratio": 1.5},
        "ar": {"rebound_pct": 0.05, "days_after_sc": 5},
        "st": {"tolerance": 0.02},
        "spring": {"low_breach_min": 0.01, "low_breach_max": 0.03, "recovery_days": 3},
        "distribution": {"volume_ratio": 1.5},
    },
    "rsi": {"overbought": 70},
}


def make_flat_df(n: int, price: float = 100.0, volume: float = 1000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "Open": [price] * n,
        "High": [price + 1] * n,
        "Low": [price - 1] * n,
        "Close": [price] * n,
        "Volume": [volume] * n,
    })


def inject_sc_row(df: pd.DataFrame, idx: int) -> pd.DataFrame:
    """指定インデックスにSC条件（出来高2倍以上・値幅1.5倍以上・陰線）を挿入。"""
    df = df.copy()
    avg_vol = df["Volume"].mean()
    avg_range = (df["High"] - df["Low"]).mean()
    df.at[idx, "Volume"] = avg_vol * 3
    df.at[idx, "High"] = df.at[idx, "High"] + avg_range * 2
    df.at[idx, "Low"] = df.at[idx, "Low"] - avg_range * 2
    df.at[idx, "Open"] = df.at[idx, "High"] - 0.5  # 陰線：Open > Close
    df.at[idx, "Close"] = df.at[idx, "Low"] + 0.5
    return df


class TestDetectSc:
    def test_no_sc_on_flat_data(self):
        df = make_flat_df(40)
        found, idx = detect_sc(df, CFG)
        assert not found

    def test_sc_detected(self):
        df = make_flat_df(40)
        df = inject_sc_row(df, 35)
        found, idx = detect_sc(df, CFG)
        assert found
        assert idx == 35


class TestDetectAr:
    def test_ar_detected(self):
        df = make_flat_df(40, price=100.0)
        sc_idx = 30
        df = inject_sc_row(df, sc_idx)
        sc_low = df.at[sc_idx, "Low"]
        # AR条件: SC後5日以内に+5%反発
        df.at[sc_idx + 2, "High"] = sc_low * 1.06
        assert detect_ar(df, sc_idx, CFG)

    def test_ar_not_detected(self):
        df = make_flat_df(40, price=100.0)
        sc_idx = 30
        df = inject_sc_row(df, sc_idx)
        # inject_sc_row で SC_low ≈ 95.0 → AR閾値 = 99.75
        # フラットデータのHigh(101)が閾値を超えるため、post-SC行のHighを下げる
        sc_low = float(df.at[sc_idx, "Low"])
        ar_threshold = sc_low * (1 + CFG["wyckoff"]["ar"]["rebound_pct"])
        days = CFG["wyckoff"]["ar"]["days_after_sc"]
        for j in range(sc_idx + 1, min(sc_idx + 1 + days, len(df))):
            df.at[j, "High"] = ar_threshold - 0.5
        assert not detect_ar(df, sc_idx, CFG)


class TestDetectSpring:
    def test_no_spring_on_flat(self):
        df = make_flat_df(30)
        assert not detect_spring(df, CFG)

    def test_spring_detected(self):
        # detect_springはbase=df.iloc[:-rec_days-1]でperiod_lowを計算。
        # rec_days=3なので base=df.iloc[:26]（n=30）、Spring候補=row26、回復=rows27-29
        n = 30
        prices = [100.0] * n
        df = pd.DataFrame({
            "Open": prices,
            "High": [p + 2 for p in prices],   # 102.0
            "Low": [p - 2 for p in prices],     # 98.0
            "Close": prices,
            "Volume": [1000.0] * n,
        })
        # Spring候補日 = row 26（base = rows 0-25、period_low = 98.0）
        spring_idx = 26
        period_low = 98.0  # rows 0-25 の Low の最小値
        period_high = 102.0  # rows 0-25 の High の最大値
        df.at[spring_idx, "Low"] = period_low * (1 - 0.015)   # 96.53（1.5%下抜け）
        df.at[spring_idx, "Volume"] = 500.0  # 平均以下
        # 回復: rows 27-29 のいずれかで period_high * 0.9 以上のClose
        df.at[spring_idx + 1, "Close"] = period_high * 0.95  # 96.9 > 91.8
        assert detect_spring(df, CFG)


class TestDetectChoch:
    def test_choch_higher_low(self):
        # detect_choch: prev_low = df.iloc[-40:-20]["Low"].min()、recent_low = df.tail(20)["Low"].min()
        # CHoCH = recent_low > prev_low（直近安値が前期安値を上回る）
        n = 60
        # rows 0-19: ダミー, rows 20-39 (prev): 低い安値75, rows 40-59 (recent): 高い安値85
        lows = [100.0] * 20 + [75.0] * 20 + [85.0] * 20
        df = pd.DataFrame({
            "Open": [100.0] * n,
            "High": [105.0] * n,
            "Low": lows,
            "Close": [100.0] * n,
            "Volume": [1000.0] * n,
        })
        assert detect_choch(df, CFG)  # recent=85 > prev=75 → True

    def test_choch_lower_low(self):
        n = 60
        # rows 20-39 (prev): 高い安値90, rows 40-59 (recent): 低い安値80
        lows = [100.0] * 20 + [90.0] * 20 + [80.0] * 20
        df = pd.DataFrame({
            "Open": [100.0] * n,
            "High": [105.0] * n,
            "Low": lows,
            "Close": [100.0] * n,
            "Volume": [1000.0] * n,
        })
        assert not detect_choch(df, CFG)  # recent=80 < prev=90 → False


class TestCheckWyckoffBuyPattern:
    def test_empty_df_returns_all_false(self):
        result = check_wyckoff_buy_pattern(pd.DataFrame(), CFG)
        assert all(not v for v in result.values())

    def test_too_short_df(self):
        df = make_flat_df(5)
        result = check_wyckoff_buy_pattern(df, CFG)
        assert all(not v for v in result.values())


class TestCheckWyckoffSellPattern:
    def test_sell_pattern_detected(self):
        n = 30
        df = pd.DataFrame({
            "Open": [100.0] * n,
            "High": [102.0] * n,
            "Low": [98.0] * n,
            "Close": [99.0] * n,      # 陰線（Close < Open）
            "Volume": [1000.0] * n,
        })
        # 最終日: 出来高を平均の2倍に設定
        df.at[n - 1, "Volume"] = 2000.0
        rsi_val = 75.0  # RSI >= 70
        assert check_wyckoff_sell_pattern(df, rsi_val, CFG)

    def test_no_sell_pattern_low_rsi(self):
        df = make_flat_df(30)
        df.at[29, "Volume"] = 3000.0
        df.at[29, "Close"] = df.at[29, "Open"] - 1  # 陰線
        assert not check_wyckoff_sell_pattern(df, 50.0, CFG)
