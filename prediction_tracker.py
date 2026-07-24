import os

import pandas as pd

# CSV全件をメモリに読み込む設計。運用が長期化してレコードが数万行を超える場合は
# SQLite等への移行を検討する（初期実装ではCSVで問題ない）。
PREDICTION_COLUMNS = [
    "prediction_id",
    "date",
    "ticker",
    "signal_type",
    "basis_price",
    "eval_due_date",
    "eval_price",
    "result",
    "status",
]


def load_predictions(path: str) -> pd.DataFrame:
    """predictions.csvを読み込む。存在しない/空の場合は空DataFrameを返す。"""
    if not os.path.exists(path):
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    try:
        df = pd.read_csv(path, dtype={"prediction_id": str, "date": str, "ticker": str,
                                       "signal_type": str, "eval_due_date": str, "status": str})
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    return df


def save_predictions(df: pd.DataFrame, path: str) -> None:
    """predictions.csvへ保存（列順を固定）。"""
    df.to_csv(path, index=False, columns=PREDICTION_COLUMNS)


def compute_eval_due_date(alert_date: str, business_days: int) -> str:
    """alert_dateからbusiness_days営業日後の日付をYYYY-MM-DD形式で返す。"""
    dates = pd.bdate_range(start=alert_date, periods=business_days + 1)
    return dates[-1].strftime("%Y-%m-%d")


def build_prediction_rows(
    candidates: list[dict],
    signal_type: str,
    date_str: str,
    business_days: int,
) -> pd.DataFrame:
    """買い/売り候補リストからpredictions.csv用の新規行を組み立てる。"""
    if not candidates:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    eval_due_date = compute_eval_due_date(date_str, business_days)
    rows = []
    for c in candidates:
        ticker = str(c["ticker"])
        rows.append({
            "prediction_id": f"{date_str}_{ticker}_{signal_type}",
            "date": date_str,
            "ticker": ticker,
            "signal_type": signal_type,
            "basis_price": float(c["close"]),
            "eval_due_date": eval_due_date,
            "eval_price": None,
            "result": None,
            "status": "pending",
        })
    return pd.DataFrame(rows, columns=PREDICTION_COLUMNS)


def append_predictions(
    existing_df: pd.DataFrame,
    new_rows_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """new_rows_dfをexisting_dfへ追記する。既存のprediction_idと重複する行はスキップする
    （同一日にワークフローを再実行しても二重記録・basis_price上書きが起きないようにするため）。
    既存行のいずれの列も変更しない（追記専用）。
    """
    if new_rows_df.empty:
        return existing_df, 0
    existing_ids = set(existing_df["prediction_id"]) if not existing_df.empty else set()
    to_add = new_rows_df[~new_rows_df["prediction_id"].isin(existing_ids)]
    n_skipped = len(new_rows_df) - len(to_add)
    if to_add.empty:
        return existing_df, n_skipped
    merged = pd.concat([existing_df, to_add], ignore_index=True)
    return merged, n_skipped


def judge_hit(
    signal_type: str,
    basis_price: float,
    eval_price: float,
    buy_hit_pct: float,
    sell_hit_pct: float,
) -> str:
    """的中("hit")/不的中("miss")を判定する純粋関数。境界値は的中側に含む。"""
    if signal_type == "buy":
        return "hit" if eval_price >= basis_price * (1 + buy_hit_pct) else "miss"
    if signal_type == "sell":
        return "hit" if eval_price <= basis_price * (1 - sell_hit_pct) else "miss"
    raise ValueError(f"unknown signal_type: {signal_type}")


def mark_due_predictions_evaluated(
    df: pd.DataFrame,
    eval_prices: dict[str, float | None],
    today_str: str,
    buy_hit_pct: float,
    sell_hit_pct: float,
) -> pd.DataFrame:
    """status=="pending"かつeval_due_date<=today_strの行を評価する。
    eval_pricesにNone/未登録のティッカーはstatus="unavailable"とし、的中率の分母から除外する
    （評価不能を無理に的中/不的中判定しない。リトライはせず永続的に除外する）。
    既存のdate/basis_price/eval_due_date列は一切書き換えない。
    """
    df = df.copy()
    # CSVから読み込むと空列(eval_price/result)はfloat64(NaN)に推論されるため、
    # 文字列("hit"/"unavailable"等)を代入できるようdtypeを明示的に揃える
    df["eval_price"] = df["eval_price"].astype("float64")
    df["result"] = df["result"].astype("object")
    df["status"] = df["status"].astype("object")
    due_mask = (df["status"] == "pending") & (df["eval_due_date"] <= today_str)
    for idx in df[due_mask].index:
        ticker = df.at[idx, "ticker"]
        price = eval_prices.get(ticker)
        if price is None:
            df.at[idx, "status"] = "unavailable"
            continue
        signal_type = df.at[idx, "signal_type"]
        basis_price = float(df.at[idx, "basis_price"])
        result = judge_hit(signal_type, basis_price, float(price), buy_hit_pct, sell_hit_pct)
        df.at[idx, "eval_price"] = round(float(price), 2)
        df.at[idx, "result"] = result
        df.at[idx, "status"] = "evaluated"
    return df


def aggregate_hit_rate(
    df: pd.DataFrame,
    signal_type: str,
    window_mode: str,
    window_value: int,
    today_str: str,
) -> dict:
    """signal_type別に的中率を集計する。status=="evaluated"のみ対象
    （pending/unavailableは分母から除外）。window_mode="count"は直近window_value件、
    "months"は直近window_valueヶ月で絞り込む。評価済み0件の場合hit_rate=Noneを返す。
    """
    if window_mode not in ("count", "months"):
        raise ValueError(f"unknown window_mode: {window_mode}")
    subset = df[(df["status"] == "evaluated") & (df["signal_type"] == signal_type)]
    subset = subset.sort_values("date")
    if window_mode == "count":
        subset = subset.tail(window_value)
    else:
        cutoff = (pd.Timestamp(today_str) - pd.DateOffset(months=window_value)).strftime("%Y-%m-%d")
        subset = subset[subset["date"] >= cutoff]
    total = len(subset)
    if total == 0:
        return {"hit_count": 0, "miss_count": 0, "total": 0, "hit_rate": None}
    hit_count = int((subset["result"] == "hit").sum())
    return {
        "hit_count": hit_count,
        "miss_count": total - hit_count,
        "total": total,
        "hit_rate": hit_count / total,
    }
