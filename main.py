import logging
import os
import sys
from datetime import datetime

import pandas as pd
import yaml

from data_fetcher import fetch_index_data, fetch_stock_data
from trend_rules import judge_trend
from screener import run_buy_screening, run_sell_screening
from notifier import send_line_message, format_buy_alert, format_sell_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    cfg = load_config()
    watchlist = pd.read_csv("watchlist.csv")
    try:
        holdings = pd.read_csv("holdings.csv")
    except Exception:
        holdings = pd.DataFrame(
            columns=["ticker", "name", "acquired_date", "shares", "sector", "market"]
        )

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not token or not user_id:
        logging.error("LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定です")
        sys.exit(1)

    # 1. セクター指数のトレンド判定
    trend_results: dict[str, str] = {}
    t_cfg = cfg["trend"]
    for idx_info in cfg["sector_indexes"]:
        df = fetch_index_data(idx_info["ticker"], cfg["data"]["history_period"])
        if df.empty:
            logging.warning(f"指数データ取得失敗: {idx_info['ticker']}")
            trend_results[idx_info["sector"]] = "データ不足"
            continue
        trend = judge_trend(
            df["Close"],
            t_cfg["ma_short"],
            t_cfg["ma_long"],
            t_cfg["momentum_threshold"],
            t_cfg["momentum_period"],
        )
        logging.info(f"{idx_info['name']}: {trend}")
        trend_results[idx_info["sector"]] = trend

    # 2. 個別銘柄データ取得（ウォッチリスト＋保有銘柄）
    holding_tickers = (
        holdings["ticker"].tolist() if not holdings.empty else []
    )
    all_tickers = list(set(watchlist["ticker"].tolist() + holding_tickers))
    stock_data = fetch_stock_data(
        all_tickers,
        cfg["data"]["history_period"],
        cfg["data"]["batch_size"],
        cfg["data"]["batch_sleep"],
    )

    # 3. スクリーニング
    date_str = datetime.now().strftime("%Y-%m-%d")
    buy_candidates = run_buy_screening(watchlist, trend_results, stock_data, cfg)
    sell_candidates = run_sell_screening(holdings, trend_results, stock_data, cfg)

    # 4. LINE通知
    line_cfg = cfg["line"]
    if buy_candidates:
        msg = format_buy_alert(buy_candidates, date_str)
        ok = send_line_message(
            msg, token, user_id, line_cfg["api_endpoint"], line_cfg["retry_count"]
        )
        logging.info(f"買い候補通知: {'成功' if ok else '失敗'} ({len(buy_candidates)}銘柄)")
    else:
        logging.info("買い候補なし")

    if sell_candidates:
        msg = format_sell_alert(sell_candidates, date_str)
        ok = send_line_message(
            msg, token, user_id, line_cfg["api_endpoint"], line_cfg["retry_count"]
        )
        logging.info(f"売り候補通知: {'成功' if ok else '失敗'} ({len(sell_candidates)}銘柄)")
    else:
        logging.info("売り候補なし")


if __name__ == "__main__":
    main()
