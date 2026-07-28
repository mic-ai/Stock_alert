import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from panic_bottom_detector import (
    PanicDetectorConfig,
    config_from_dict,
    _selling_climax_flags,
    build_market_aggregates,
    compute_market_panic_and_bottom,
)


class TestConfigFromDict:
    def test_ignores_unknown_keys(self):
        cfg = config_from_dict(
            {
                "alert_score_threshold": 5.0,
                "data_period": "1y",  # dataclassにないキー
                "low_reliability_threshold": 0.5,  # dataclassにないキー
            }
        )
        assert cfg.alert_score_threshold == 5.0

    def test_defaults_when_empty(self):
        cfg = config_from_dict({})
        assert cfg == PanicDetectorConfig()


class TestSellingClimaxFlags:
    def _make_ohlcv(self, closes, highs, lows, volumes):
        return pd.DataFrame(
            {
                "Close": closes,
                "High": highs,
                "Low": lows,
                "Volume": volumes,
            }
        )

    def test_climax_day_flagged(self):
        # volume_window内に当日自身も含まれる(自己参照)ため、z-scoreの理論上限は
        # (window-1)/sqrt(window)。window=5だとthreshold=2.0を超えられないため、
        # window=10で検証する。
        cfg = PanicDetectorConfig(volume_window=10, volume_z_threshold=2.0, range_multiplier=1.5, close_near_low_threshold=0.3)
        n_normal = 9
        closes = [100.0] * n_normal
        highs = [101.0] * n_normal
        lows = [99.0] * n_normal
        volumes = [1000] * n_normal

        # クライマックス日: 出来高急増・値幅拡大・安値圏引け
        closes.append(80.0)
        highs.append(100.0)
        lows.append(79.0)
        volumes.append(30000)

        df = self._make_ohlcv(closes, highs, lows, volumes)
        flags = _selling_climax_flags(df, cfg)

        assert flags.iloc[-1] == True  # noqa: E712
        assert flags.iloc[2] == False  # noqa: E712 通常日は非該当

    def test_normal_days_never_flagged(self):
        cfg = PanicDetectorConfig(volume_window=5)
        closes = [100.0] * 10
        highs = [101.0] * 10
        lows = [99.0] * 10
        volumes = [1000, 1010, 990, 1005, 995, 1000, 1010, 990, 1005, 995]
        df = self._make_ohlcv(closes, highs, lows, volumes)
        flags = _selling_climax_flags(df, cfg)
        assert not flags.any()


class TestBuildMarketAggregates:
    def test_averages_across_tickers(self):
        idx = pd.date_range("2026-01-01", periods=5, freq="B")
        df_a = pd.DataFrame(
            {
                "Close": [100, 99, 98, 97, 96],
                "High": [101, 100, 99, 98, 97],
                "Low": [99, 98, 97, 96, 95],
                "Volume": [1000, 1000, 1000, 1000, 1000],
                "RSI_14": [50, 40, 30, 20, 10],
            },
            index=idx,
        )
        df_b = pd.DataFrame(
            {
                "Close": [200, 202, 204, 206, 208],
                "High": [201, 203, 205, 207, 209],
                "Low": [199, 201, 203, 205, 207],
                "Volume": [2000, 2000, 2000, 2000, 2000],
                "RSI_14": [60, 65, 70, 75, 80],
            },
            index=idx,
        )
        cfg = PanicDetectorConfig(volume_window=3, rsi_oversold_threshold=20.0)
        market = build_market_aggregates({"A": df_a, "B": df_b}, cfg)

        assert list(market.columns) == ["jp_avg_return", "climax_breadth", "rsi_breadth"]
        # 最終日: Aのみ RSI<20 (10) なので breadth=0.5
        assert market["rsi_breadth"].iloc[-1] == 0.5


class TestComputeMarketPanicAndBottom:
    def _base_market(self, n=13):
        idx = pd.date_range("2026-01-01", periods=n, freq="B")
        market = pd.DataFrame(
            {
                "jp_avg_return": [0.001] * n,
                "climax_breadth": [0.05] * n,
                "rsi_breadth": [0.05] * n,
                "decoupling": [False] * n,
            },
            index=idx,
        )
        return market

    def test_normal_market_no_alerts(self):
        cfg = PanicDetectorConfig()
        market = self._base_market(10)
        result = compute_market_panic_and_bottom(market, cfg)
        assert not result["panic_alert"].any()
        assert not result["bottom_candidate"].any()

    def test_panic_scenario_triggers_alert(self):
        cfg = PanicDetectorConfig()
        market = self._base_market(11)
        # 直近3日で急落・出来高急増・売られ過ぎ・デカップリングが重なる
        market.loc[market.index[8], ["jp_avg_return", "climax_breadth", "rsi_breadth", "decoupling"]] = [
            -0.06, 0.30, 0.10, False,
        ]
        market.loc[market.index[9], ["jp_avg_return", "climax_breadth", "rsi_breadth", "decoupling"]] = [
            -0.06, 0.30, 0.10, False,
        ]
        market.loc[market.index[10], ["jp_avg_return", "climax_breadth", "rsi_breadth", "decoupling"]] = [
            -0.06, 0.50, 0.40, True,
        ]
        result = compute_market_panic_and_bottom(market, cfg)
        latest = result.iloc[-1]
        # decoupling(2.0) + climax(2.0) + rsi(1.0) + consecutive_decline(1.0) = 6.0 >= 4.0
        assert latest["market_panic_score"] == 6.0
        assert latest["panic_alert"] == True  # noqa: E712

    def test_bottom_candidate_after_panic_recedes(self):
        cfg = PanicDetectorConfig()
        market = self._base_market(13)
        # day8-10: パニックのピーク(day10がピーク)
        for i in (8, 9):
            market.loc[market.index[i], ["jp_avg_return", "climax_breadth", "rsi_breadth", "decoupling"]] = [
                -0.06, 0.30, 0.10, False,
            ]
        market.loc[market.index[10], ["jp_avg_return", "climax_breadth", "rsi_breadth", "decoupling"]] = [
            -0.06, 0.50, 0.40, True,
        ]
        # day11-12: 沈静化(breadth縮小・プラス転換が2日連続)
        for i in (11, 12):
            market.loc[market.index[i], ["jp_avg_return", "climax_breadth", "rsi_breadth", "decoupling"]] = [
                0.01, 0.10, 0.05, False,
            ]

        result = compute_market_panic_and_bottom(market, cfg)
        peak = result.iloc[10]
        latest = result.iloc[-1]

        assert peak["panic_alert"] == True  # noqa: E712
        assert latest["panic_alert"] == False  # noqa: E712
        assert latest["bottom_candidate"] == True  # noqa: E712
