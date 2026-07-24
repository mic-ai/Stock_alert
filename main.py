import logging
import os
import sys

import pandas as pd
import yaml

from data_fetcher import fetch_index_data, fetch_stock_data
from date_utils import today_jst
from trend_rules import judge_trend
from screener import run_buy_screening, run_sell_screening
from notifier import send_email, format_buy_alert, format_sell_alert
from prediction_tracker import (
    load_predictions,
    save_predictions,
    build_prediction_rows,
    append_predictions,
)

PREDICTIONS_PATH = "predictions.csv"

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

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    to_address = os.environ.get("NOTIFY_TO_EMAIL", gmail_user)
    if not gmail_user or not gmail_app_password:
        logging.error("GMAIL_USER / GMAIL_APP_PASSWORD が未設定です")
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
    holding_tickers = holdings["ticker"].tolist() if not holdings.empty else []
    all_tickers = list(set(watchlist["ticker"].tolist() + holding_tickers))
    stock_data = fetch_stock_data(
        all_tickers,
        cfg["data"]["history_period"],
        cfg["data"]["batch_size"],
        cfg["data"]["batch_sleep"],
    )

    # 3. スクリーニング
    date_str = today_jst()
    buy_candidates = run_buy_screening(watchlist, trend_results, stock_data, cfg)
    sell_candidates = run_sell_screening(holdings, trend_results, stock_data, cfg)

    # 4. 予測ログへの記録（メール送信の成否に関わらず記録する。
    #    追跡対象はスクリーニングルールの精度であり、SMTP成否ではないため）
    try:
        e_cfg = cfg["evaluation"]
        predictions_df = load_predictions(PREDICTIONS_PATH)
        buy_rows = build_prediction_rows(buy_candidates, "buy", date_str, e_cfg["business_days"])
        sell_rows = build_prediction_rows(sell_candidates, "sell", date_str, e_cfg["business_days"])
        predictions_df, n_skipped_buy = append_predictions(predictions_df, buy_rows)
        predictions_df, n_skipped_sell = append_predictions(predictions_df, sell_rows)
        save_predictions(predictions_df, PREDICTIONS_PATH)
        logging.info(
            f"[main] predictions.csv更新: 買い{len(buy_rows) - n_skipped_buy}件追加"
            f"（重複{n_skipped_buy}件スキップ）、売り{len(sell_rows) - n_skipped_sell}件追加"
            f"（重複{n_skipped_sell}件スキップ）"
        )
    except Exception as e:
        logging.warning(f"[main] predictions.csv更新失敗: {e}")

    # 5. メール通知（候補ゼロでも毎日日次レポートを送信）
    retry = cfg["email"]["retry_count"]
    body_parts = []

    if buy_candidates:
        _, buy_body = format_buy_alert(buy_candidates, date_str)
        body_parts.append(buy_body)
        logging.info(f"買い候補: {len(buy_candidates)}銘柄")
    else:
        body_parts.append("【買い候補】\nなし\n")
        logging.info("買い候補なし")

    if sell_candidates:
        _, sell_body = format_sell_alert(sell_candidates, date_str)
        body_parts.append(sell_body)
        logging.info(f"売り候補: {len(sell_candidates)}銘柄")
    else:
        body_parts.append("【売り候補】\nなし\n")
        logging.info("売り候補なし")

    subject = f"【株スクリーニング日次レポート】{date_str} 買い{len(buy_candidates)}件 / 売り{len(sell_candidates)}件"
    body = "\n".join(body_parts)
    ok = send_email(body, subject, gmail_user, gmail_app_password, to_address, retry)
    logging.info(f"日次レポート送信: {'成功' if ok else '失敗'}")


if __name__ == "__main__":
    main()
