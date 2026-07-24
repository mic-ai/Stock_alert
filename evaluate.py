import logging
import os
import sys

import yaml

from data_fetcher import fetch_stock_data
from date_utils import today_jst
from notifier import send_email, format_evaluation_summary
from prediction_tracker import (
    load_predictions,
    save_predictions,
    mark_due_predictions_evaluated,
    aggregate_hit_rate,
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
    e_cfg = cfg["evaluation"]
    if e_cfg["window_mode"] not in ("count", "months"):
        logging.error(f"evaluation.window_mode が不正です: {e_cfg['window_mode']}")
        sys.exit(1)

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    to_address = os.environ.get("NOTIFY_TO_EMAIL", gmail_user)
    if not gmail_user or not gmail_app_password:
        logging.error("GMAIL_USER / GMAIL_APP_PASSWORD が未設定です")
        sys.exit(1)

    today_str = today_jst()
    predictions_df = load_predictions(PREDICTIONS_PATH)

    due_mask = (predictions_df["status"] == "pending") & (predictions_df["eval_due_date"] <= today_str)
    due_tickers = sorted(set(predictions_df.loc[due_mask, "ticker"]))

    if not due_tickers:
        logging.info("[evaluate] 本日評価対象の予測はありません")
        return

    stock_data = fetch_stock_data(
        due_tickers,
        e_cfg["fetch_period"],
        cfg["data"]["batch_size"],
        cfg["data"]["batch_sleep"],
    )
    eval_prices: dict[str, float | None] = {}
    for ticker in due_tickers:
        df = stock_data.get(ticker)
        if df is None or df.empty:
            eval_prices[ticker] = None
        else:
            eval_prices[ticker] = float(df["Close"].iloc[-1])

    predictions_df = mark_due_predictions_evaluated(
        predictions_df,
        eval_prices,
        today_str,
        e_cfg["buy_hit_pct"],
        e_cfg["sell_hit_pct"],
    )
    save_predictions(predictions_df, PREDICTIONS_PATH)
    logging.info(f"[evaluate] {len(due_tickers)}銘柄分の予測を評価しました")

    agg = {
        "buy": aggregate_hit_rate(predictions_df, "buy", e_cfg["window_mode"], e_cfg["window_value"], today_str),
        "sell": aggregate_hit_rate(predictions_df, "sell", e_cfg["window_mode"], e_cfg["window_value"], today_str),
    }
    subject, body = format_evaluation_summary(agg, today_str)
    retry = cfg["email"]["retry_count"]
    ok = send_email(body, subject, gmail_user, gmail_app_password, to_address, retry)
    logging.info(f"的中率サマリー通知: {'成功' if ok else '失敗'}")


if __name__ == "__main__":
    main()
