import time
import logging
import pandas as pd
import yfinance as yf


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinanceが単一銘柄でもMultiIndexカラムを返す場合があるため、Tickerレベルを除去して平坦化する。"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel("Ticker")
    return df


def fetch_index_data(ticker: str, period: str) -> pd.DataFrame:
    """セクター指数の価格・出来高データを取得。失敗時は空DataFrameを返す。"""
    try:
        df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if df.empty:
            logging.warning(f"[data_fetcher] {ticker}: データ空（レート制限またはティッカー誤り）")
            return df
        return _flatten_columns(df)
    except Exception as e:
        logging.warning(f"[data_fetcher] {ticker}: 取得失敗 - {e}")
        return pd.DataFrame()


def fetch_stock_data(
    tickers: list[str],
    period: str,
    batch_size: int,
    batch_sleep: float,
) -> dict[str, pd.DataFrame]:
    """個別銘柄データをbatch_sizeずつ取得。バッチ間batch_sleep秒スリープ。"""
    result: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        try:
            raw = yf.download(
                batch,
                period=period,
                group_by="ticker",
                progress=False,
                auto_adjust=True,
            )
            for ticker in batch:
                try:
                    df = raw[ticker] if len(batch) > 1 else raw
                    if df.empty:
                        logging.warning(f"[data_fetcher] {ticker}: データ空")
                        result[ticker] = pd.DataFrame()
                    else:
                        result[ticker] = _flatten_columns(df)
                except Exception:
                    logging.warning(f"[data_fetcher] {ticker}: 抽出失敗")
                    result[ticker] = pd.DataFrame()
        except Exception as e:
            logging.warning(f"[data_fetcher] バッチ取得失敗 {batch}: {e}")
            for t in batch:
                result[t] = pd.DataFrame()
        if i + batch_size < len(tickers):
            time.sleep(batch_sleep)
    return result
