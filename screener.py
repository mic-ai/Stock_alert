import logging
import pandas as pd
from indicators import calculate_rsi
from wyckoff_rules import check_wyckoff_buy_pattern, check_wyckoff_sell_pattern


def run_buy_screening(
    watchlist_df: pd.DataFrame,
    trend_results: dict[str, str],
    stock_data: dict[str, pd.DataFrame],
    cfg: dict,
) -> list[dict]:
    """上昇トレンド業種内の銘柄に対してワイコフ買いパターンをチェック。"""
    candidates: list[dict] = []
    up_sectors = {s for s, t in trend_results.items() if t == "上昇トレンド"}
    if not up_sectors:
        logging.info("[screener] 上昇トレンドの業種なし。買いスクリーニングをスキップ。")
        return candidates
    targets = watchlist_df[watchlist_df["sector"].isin(up_sectors)]
    for _, row in targets.iterrows():
        ticker = str(row["ticker"])
        df = stock_data.get(ticker, pd.DataFrame())
        if df.empty:
            continue
        rsi_series = calculate_rsi(df["Close"], cfg["rsi"]["period"])
        if rsi_series is None or rsi_series.empty:
            continue
        rsi_val = float(rsi_series.iloc[-1])
        if rsi_val >= cfg["rsi"]["overbought"]:
            continue
        patterns = check_wyckoff_buy_pattern(df, cfg)
        matched = [k for k, v in patterns.items() if v]
        if matched:
            candidates.append({
                "ticker": ticker,
                "name": str(row.get("name", ticker)),
                "rsi": round(rsi_val, 1),
                "patterns": matched,
                "sector": str(row["sector"]),
                "market": str(row["market"]),
            })
    return candidates


def run_sell_screening(
    holdings_df: pd.DataFrame,
    trend_results: dict[str, str],
    stock_data: dict[str, pd.DataFrame],
    cfg: dict,
) -> list[dict]:
    """保有銘柄に対して業種下降トレンドまたは分配パターンをチェック。"""
    candidates: list[dict] = []
    if holdings_df.empty:
        return candidates
    down_sectors = {s for s, t in trend_results.items() if t == "下降トレンド"}
    for _, row in holdings_df.iterrows():
        ticker = str(row["ticker"])
        df = stock_data.get(ticker, pd.DataFrame())
        if df.empty:
            continue
        rsi_series = calculate_rsi(df["Close"], cfg["rsi"]["period"])
        rsi_val: float | None = None
        if rsi_series is not None and not rsi_series.empty:
            rsi_val = float(rsi_series.iloc[-1])
        sector_down = str(row.get("sector", "")) in down_sectors
        dist_pattern = (
            check_wyckoff_sell_pattern(df, rsi_val, cfg) if rsi_val is not None else False
        )
        if sector_down or dist_pattern:
            reason: list[str] = []
            if sector_down:
                reason.append("業種下降トレンド")
            if dist_pattern:
                reason.append("分配パターン(RSI高＋出来高急増陰線)")
            candidates.append({
                "ticker": ticker,
                "name": str(row.get("name", ticker)),
                "rsi": round(rsi_val, 1) if rsi_val is not None else "N/A",
                "reason": reason,
                "sector": str(row.get("sector", "")),
                "market": str(row.get("market", "")),
            })
    return candidates
