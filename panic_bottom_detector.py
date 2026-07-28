# -*- coding: utf-8 -*-
"""
panic_bottom_detector.py
=========================
市場全体のパニック売り・底値圏検出モジュール(watchlist.csv全体の集計ベース)

【設計方針】
個別銘柄の急落判定ではなく、watchlist.csv に登録された監視銘柄群「全体」の値動きから、
市場規模のパニック(株価恐慌のような状態)とその底を検出することを目的とする。

構成する3指標(すべてwatchlist全体の集計値として計算):
  ①クロス市場デカップリング・スコア
      watchlist全体の平均騰落率(jp_avg_return)が急落している一方で、
      米国主要指数(S&P500 / SOX)が連動していない状態を検出する。
  ②セリング・クライマックス breadth(幅)
      watchlist内の各銘柄についてSelling Climax(出来高急増+値幅拡大+安値圏引け)を個別判定し、
      「同日に何%の銘柄が該当したか」を市場規模のパニックの強さとして集計する。
  ③RSI極端乖離 breadth + 市場平均の連続急落
      watchlist内の何%の銘柄がRSI<20(極端な売られ過ぎ)かを集計し、
      あわせて watchlist全体の平均騰落率が短期間に大きく下落を繰り返しているかを確認する。

これらを合成した market_panic_score に加えて、
パニックがピークを付けたあとの「沈静化」を検出する bottom_candidate フラグを提供する
(Wyckoff法の Selling Climax → Automatic Rally → Secondary Test の考え方を単純化したもの)。

【前提・既存パイプラインとの統合】
- watchlist.csv には少なくとも 'ticker' 列(yfinance形式のティッカー、日本株は "XXXX.T")が
  含まれている前提。実際の列名が異なる場合は load_watchlist() を調整すること。
- データ取得は data_fetcher.fetch_stock_data() / fetch_index_data() を再利用する
  (20銘柄ずつのバッチ処理+バッチ間スリープ、MultiIndexカラムのフラット化、
  取得失敗時のログ出力を既存実装から引き継ぐため)。
- RSI(Wilder 14日)は pandas-ta ではなく indicators.calculate_rsi() を使う
  (pandas-ta はGitHub Actions環境でインストールできないため、本プロジェクトの
  既存パイプラインから既に除外されている)。

【注意】
- 本モジュールで使う閾値は経験則に基づく初期値であり、有効性は保証されません。
  運用しながら調整してください(config.yaml の panic_detector セクション)。
- 投資助言を目的としたものではありません。
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Optional

import pandas as pd

from data_fetcher import fetch_index_data, fetch_stock_data
from indicators import calculate_rsi


# ---------------------------------------------------------------------------
# 設定(閾値) - config.yaml の panic_detector セクションから読み込む想定
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PanicDetectorConfig:
    # ①クロス市場デカップリング
    us_index_ticker: str = "^GSPC"        # S&P500
    sox_index_ticker: str = "^SOX"        # フィラデルフィア半導体指数
    jp_drop_threshold: float = -0.02      # watchlist平均騰落率がこれ以下で「急落」とみなす
    us_flat_threshold: float = -0.005     # 米国側がこれより下がっていなければ「反応なし」

    # ②セリング・クライマックス(個別銘柄判定用の閾値)
    volume_window: int = 60
    volume_z_threshold: float = 2.0
    range_multiplier: float = 1.5
    close_near_low_threshold: float = 0.3
    climax_breadth_threshold: float = 0.25   # watchlistの何%が同日該当すれば「市場規模」とみなすか

    # ③RSI極端乖離 + 連続急落
    rsi_oversold_threshold: float = 20.0
    rsi_oversold_breadth_threshold: float = 0.30  # watchlistの何%がRSI<20か
    decline_day_threshold: float = -0.05          # watchlist平均が1日でこれ以下の下落
    decline_lookback_days: int = 5
    decline_min_occurrences: int = 2

    # 総合スコアの重み・発火閾値
    weight_decoupling: float = 2.0
    weight_climax_breadth: float = 2.0
    weight_rsi_breadth: float = 1.0
    weight_consecutive_decline: float = 1.0
    alert_score_threshold: float = 4.0

    # 底打ち候補判定
    bottom_lookback_days: int = 10           # 直近何営業日以内のパニックピークを見るか
    bottom_confirm_days: int = 2             # 平均騰落率が何日連続でプラスなら底打ち候補とするか
    bottom_breadth_decline_ratio: float = 0.5  # クライマックスbreadthがピーク比でどこまで縮小したか


def config_from_dict(d: dict) -> PanicDetectorConfig:
    """config.yaml の panic_detector セクション(dict)から PanicDetectorConfig を組み立てる。
    dataclassにないキー(data_period等、呼び出し側で個別に使う値)は無視する。
    """
    field_names = {f.name for f in dataclasses.fields(PanicDetectorConfig)}
    return PanicDetectorConfig(**{k: v for k, v in d.items() if k in field_names})


# ---------------------------------------------------------------------------
# データ取得(既存の data_fetcher を再利用)
# ---------------------------------------------------------------------------

def load_watchlist(csv_path: str, ticker_column: str = "ticker") -> list[str]:
    """watchlist.csv からティッカー一覧を読み込む。列名が異なる場合は ticker_column を指定。"""
    df = pd.read_csv(csv_path)
    if ticker_column not in df.columns:
        raise KeyError(
            f"'{ticker_column}' 列が見つかりません。実際の列名: {list(df.columns)}"
        )
    return df[ticker_column].dropna().unique().tolist()


def fetch_watchlist_ohlcv(
    tickers: list[str],
    period: str,
    batch_size: int,
    batch_sleep: float,
) -> dict[str, pd.DataFrame]:
    """
    watchlist内の各銘柄について日足OHLCV + RSI_14 を取得する。
    data_fetcher.fetch_stock_data() でバッチ取得(レート制限対策込み)した上でRSIを付与する。
    戻り値: {ticker: DataFrame}(取得失敗銘柄は含まれない)
    """
    raw = fetch_stock_data(tickers, period, batch_size, batch_sleep)

    data: dict[str, pd.DataFrame] = {}
    for ticker, df in raw.items():
        if df.empty:
            continue
        df = df.copy()
        df["RSI_14"] = calculate_rsi(df["Close"], length=14)
        df = df.dropna(subset=["RSI_14"])
        if df.empty:
            continue
        data[ticker] = df

    n_failed = len(tickers) - len(data)
    if n_failed:
        logging.warning(
            f"[panic_bottom_detector] {n_failed}/{len(tickers)}銘柄のデータ取得・RSI計算に失敗"
        )
    return data


def fetch_index_returns(ticker: str, period: str) -> Optional[pd.Series]:
    """指数の日次騰落率のSeriesを返す。取得失敗時は None(ログ出力あり)。"""
    df = fetch_index_data(ticker, period)
    if df.empty:
        logging.warning(f"[panic_bottom_detector] 指数データ取得失敗: {ticker}")
        return None
    return df["Close"].pct_change()


# ---------------------------------------------------------------------------
# ②セリング・クライマックス(個別銘柄判定 → 市場breadthに集計)
# ---------------------------------------------------------------------------

def _selling_climax_flags(df: pd.DataFrame, cfg: PanicDetectorConfig) -> pd.Series:
    """1銘柄分のOHLCVからSelling Climax該当日をブールSeriesで返す。"""
    vol_mean = df["Volume"].rolling(cfg.volume_window).mean()
    vol_std = df["Volume"].rolling(cfg.volume_window).std()
    vol_zscore = (df["Volume"] - vol_mean) / vol_std

    day_range_pct = (df["High"] - df["Low"]) / df["Close"]
    range_avg = day_range_pct.rolling(cfg.volume_window).mean()

    high_low_span = (df["High"] - df["Low"]).replace(0, pd.NA)
    close_position = (df["Close"] - df["Low"]) / high_low_span

    flags = (
        (vol_zscore > cfg.volume_z_threshold)
        & (day_range_pct > range_avg * cfg.range_multiplier)
        & (close_position < cfg.close_near_low_threshold)
    )
    return flags.fillna(False)


# ---------------------------------------------------------------------------
# 市場全体の集計データフレーム構築
# ---------------------------------------------------------------------------

def build_market_aggregates(
    data: dict[str, pd.DataFrame],
    cfg: PanicDetectorConfig,
) -> pd.DataFrame:
    """
    watchlist全銘柄のデータから、市場全体(集計)の日次データフレームを構築する。

    Returns:
        列: jp_avg_return, climax_breadth, rsi_breadth
        (日付インデックスはいずれかの銘柄でデータがある日の和集合。各列は
        skipna=Trueで計算するため、JP/US混在で市場ごとの営業日が異なっても、
        その日にデータがある銘柄のみで平均・breadthが計算される)
    """
    returns = {}
    climax_flags = {}
    rsi_oversold_flags = {}

    for ticker, df in data.items():
        returns[ticker] = df["Close"].pct_change()
        climax_flags[ticker] = _selling_climax_flags(df, cfg)
        rsi_oversold_flags[ticker] = df["RSI_14"] < cfg.rsi_oversold_threshold

    returns_df = pd.DataFrame(returns)
    climax_df = pd.DataFrame(climax_flags)
    rsi_df = pd.DataFrame(rsi_oversold_flags)

    common_index = returns_df.dropna(how="all").index

    market = pd.DataFrame(index=common_index)
    market["jp_avg_return"] = returns_df.loc[common_index].mean(axis=1, skipna=True)
    market["climax_breadth"] = climax_df.reindex(common_index).mean(axis=1, skipna=True)
    market["rsi_breadth"] = rsi_df.reindex(common_index).mean(axis=1, skipna=True)

    return market


# ---------------------------------------------------------------------------
# ①クロス市場デカップリングを時系列に付与
# ---------------------------------------------------------------------------

def attach_decoupling(market: pd.DataFrame, cfg: PanicDetectorConfig) -> pd.DataFrame:
    """米国指数の騰落率を取得し、市場集計データフレームに decoupling 列を追加する。"""
    us_returns = fetch_index_returns(cfg.us_index_ticker, period="1y")
    sox_returns = fetch_index_returns(cfg.sox_index_ticker, period="1y")

    out = market.copy()
    out["us_return"] = us_returns.reindex(out.index) if us_returns is not None else pd.NA
    out["sox_return"] = sox_returns.reindex(out.index) if sox_returns is not None else pd.NA

    jp_is_dropping = out["jp_avg_return"] <= cfg.jp_drop_threshold
    us_is_flat = (out["us_return"] > cfg.us_flat_threshold) & (out["sox_return"] > cfg.us_flat_threshold)

    out["decoupling"] = (jp_is_dropping & us_is_flat).fillna(False)
    return out


# ---------------------------------------------------------------------------
# 総合パニックスコア + 底打ち候補判定
# ---------------------------------------------------------------------------

def compute_market_panic_and_bottom(
    market: pd.DataFrame,
    cfg: PanicDetectorConfig = PanicDetectorConfig(),
) -> pd.DataFrame:
    """
    市場集計データフレーム(jp_avg_return, climax_breadth, rsi_breadth, decoupling)から、
    market_panic_score / panic_alert / bottom_candidate を算出する。
    """
    out = market.copy()

    climax_flag = out["climax_breadth"] >= cfg.climax_breadth_threshold
    rsi_flag = out["rsi_breadth"] >= cfg.rsi_oversold_breadth_threshold

    big_drop_day = out["jp_avg_return"] < cfg.decline_day_threshold
    consecutive_decline = (
        big_drop_day.rolling(cfg.decline_lookback_days).sum() >= cfg.decline_min_occurrences
    )
    out["consecutive_decline"] = consecutive_decline.fillna(False)

    out["market_panic_score"] = (
        out["decoupling"].astype(int) * cfg.weight_decoupling
        + climax_flag.astype(int) * cfg.weight_climax_breadth
        + rsi_flag.astype(int) * cfg.weight_rsi_breadth
        + out["consecutive_decline"].astype(int) * cfg.weight_consecutive_decline
    )
    out["panic_alert"] = out["market_panic_score"] >= cfg.alert_score_threshold

    # --- 底打ち候補判定 ---
    # 直近 bottom_lookback_days 以内にパニック閾値超えがあったか
    rolling_peak_score = out["market_panic_score"].rolling(cfg.bottom_lookback_days, min_periods=1).max()
    had_recent_panic = rolling_peak_score >= cfg.alert_score_threshold

    # 同ウィンドウ内でのクライマックスbreadthのピークに対し、現在どこまで縮小したか
    rolling_peak_breadth = out["climax_breadth"].rolling(cfg.bottom_lookback_days, min_periods=1).max()
    climax_receding = out["climax_breadth"] <= (rolling_peak_breadth * cfg.bottom_breadth_decline_ratio)

    # 市場平均騰落率が複数日連続でプラス転換しているか
    positive_streak = (
        (out["jp_avg_return"] > 0).rolling(cfg.bottom_confirm_days).sum() >= cfg.bottom_confirm_days
    )

    out["bottom_candidate"] = (
        had_recent_panic & climax_receding & positive_streak & (~out["panic_alert"])
    ).fillna(False)

    return out


# ---------------------------------------------------------------------------
# 既存パイプライン(main.py)から呼び出すエントリーポイント
# ---------------------------------------------------------------------------

def get_market_panic_status(
    tickers: list[str],
    cfg: PanicDetectorConfig,
    period: str = "1y",
    batch_size: int = 20,
    batch_sleep: float = 1.0,
    low_reliability_threshold: float = 0.5,
) -> Optional[dict]:
    """
    watchlistのティッカー一覧から市場パニック判定を行い、最新日の状態をdictで返す。
    データが1件も取得できなかった場合は None を返す(呼び出し側でログ・スキップ処理する)。
    """
    data = fetch_watchlist_ohlcv(tickers, period, batch_size, batch_sleep)
    n_total = len(tickers)
    n_fetched = len(data)

    if not data:
        logging.warning("[panic_bottom_detector] watchlistの取得データが空のため判定不能")
        return None

    market = build_market_aggregates(data, cfg)
    market = attach_decoupling(market, cfg)
    result = compute_market_panic_and_bottom(market, cfg)
    latest = result.iloc[-1]

    return {
        "market_panic_score": float(latest["market_panic_score"]),
        "alert_score_threshold": cfg.alert_score_threshold,
        "panic_alert": bool(latest["panic_alert"]),
        "bottom_candidate": bool(latest["bottom_candidate"]),
        "decoupling": bool(latest["decoupling"]),
        "climax_breadth": float(latest["climax_breadth"]),
        "rsi_breadth": float(latest["rsi_breadth"]),
        "consecutive_decline": bool(latest["consecutive_decline"]),
        "jp_avg_return": float(latest["jp_avg_return"]),
        "n_fetched": n_fetched,
        "n_total": n_total,
        "low_reliability": n_fetched < n_total * low_reliability_threshold,
    }


if __name__ == "__main__":
    # 手動動作確認用(実運用は main.py 経由)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _tickers = load_watchlist("watchlist.csv")
    _status = get_market_panic_status(_tickers, PanicDetectorConfig())
    print(_status)
