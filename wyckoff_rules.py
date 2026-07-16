import pandas as pd
from indicators import calculate_volume_ma, calculate_price_range


def detect_sc(df: pd.DataFrame, cfg: dict) -> tuple[bool, int | None]:
    """SC（セリングクライマックス）を直近lookback日以内で検出。

    条件: 出来高が20日平均の2倍以上 AND 日中値幅が20日平均の1.5倍以上 AND 陰線
    """
    lookback = cfg["wyckoff"]["lookback"]
    vol_ratio = cfg["wyckoff"]["sc"]["volume_ratio"]
    range_ratio = cfg["wyckoff"]["sc"]["range_ratio"]
    if len(df) < lookback:
        return False, None
    vol_ma = calculate_volume_ma(df["Volume"], lookback)
    range_ma = calculate_price_range(df).rolling(lookback).mean()
    target = df.tail(lookback)
    for i in range(len(target) - 1, -1, -1):
        abs_idx = len(df) - lookback + i
        row = target.iloc[i]
        if (
            row["Volume"] >= vol_ma.iloc[abs_idx] * vol_ratio
            and (row["High"] - row["Low"]) >= range_ma.iloc[abs_idx] * range_ratio
            and row["Close"] < row["Open"]
        ):
            return True, abs_idx
    return False, None


def detect_ar(df: pd.DataFrame, sc_idx: int, cfg: dict) -> bool:
    """AR（オートマチックラリー）: SC後days_after_sc日以内にSC安値からrebound_pct%以上反発。"""
    days = cfg["wyckoff"]["ar"]["days_after_sc"]
    pct = cfg["wyckoff"]["ar"]["rebound_pct"]
    sc_low = df.iloc[sc_idx]["Low"]
    window = df.iloc[sc_idx + 1 : sc_idx + 1 + days]
    return bool((window["High"] >= sc_low * (1 + pct)).any())


def detect_st(df: pd.DataFrame, sc_idx: int, cfg: dict) -> bool:
    """ST（セカンドテスト）: AR後にSC安値の±tolerance以内まで再下落し、その後反発。"""
    tol = cfg["wyckoff"]["st"]["tolerance"]
    sc_low = df.iloc[sc_idx]["Low"]
    after = df.iloc[sc_idx + 1 :]
    if after.empty:
        return False
    touched = (
        (after["Low"] >= sc_low * (1 - tol)) & (after["Low"] <= sc_low * (1 + tol))
    ).any()
    if not touched:
        return False
    return bool(after.iloc[-1]["Close"] > after.iloc[-1]["Open"])


def detect_spring(df: pd.DataFrame, cfg: dict) -> bool:
    """Spring: 直近lookback日安値を1〜3%下回った後、recovery_days日以内にレンジ上限近くへ戻す。

    出来高はSpring発生日に平均以下であること。
    """
    lookback = cfg["wyckoff"]["lookback"]
    lo_min = cfg["wyckoff"]["spring"]["low_breach_min"]
    lo_max = cfg["wyckoff"]["spring"]["low_breach_max"]
    rec_days = cfg["wyckoff"]["spring"]["recovery_days"]
    if len(df) < lookback + rec_days + 2:
        return False
    # Spring候補日の前の期間のみでレンジを計算（候補日自体を除外）
    base = df.iloc[: len(df) - rec_days - 1]
    period_low = base.tail(lookback)["Low"].min()
    period_high = base.tail(lookback)["High"].max()
    vol_ma = calculate_volume_ma(df["Volume"], lookback).iloc[-rec_days - 1]
    candidates = df.tail(rec_days + 1)
    for i in range(len(candidates) - rec_days):
        row = candidates.iloc[i]
        breach = (
            row["Low"] < period_low * (1 - lo_min)
            and row["Low"] >= period_low * (1 - lo_max)
        )
        if not breach:
            continue
        recovery_window = candidates.iloc[i + 1 : i + 1 + rec_days]
        recovered = bool((recovery_window["Close"] >= period_high * 0.9).any())
        low_vol = bool(row["Volume"] <= vol_ma)
        if recovered and low_vol:
            return True
    return False


def detect_choch(df: pd.DataFrame, cfg: dict) -> bool:
    """CHoCH（Change of Character）: 直近スイング安値が前期スイング安値を上回る（Higher Low）。"""
    lookback = cfg["wyckoff"]["lookback"]
    if len(df) < lookback * 2:
        return False
    prev_low = df.iloc[-lookback * 2 : -lookback]["Low"].min()
    recent_low = df.tail(lookback)["Low"].min()
    return bool(recent_low > prev_low)


def check_wyckoff_buy_pattern(df: pd.DataFrame, cfg: dict) -> dict[str, bool]:
    """買いパターン判定。Spring / CHoCH / SC→AR→ST シーケンスをそれぞれ検出。"""
    result: dict[str, bool] = {"spring": False, "choch": False, "sc_ar_st": False}
    if df.empty or len(df) < cfg["wyckoff"]["lookback"]:
        return result
    result["spring"] = detect_spring(df, cfg)
    result["choch"] = detect_choch(df, cfg)
    sc_found, sc_idx = detect_sc(df, cfg)
    if sc_found and sc_idx is not None:
        ar = detect_ar(df, sc_idx, cfg)
        st = detect_st(df, sc_idx, cfg) if ar else False
        result["sc_ar_st"] = ar and st
    return result


def check_wyckoff_sell_pattern(df: pd.DataFrame, rsi_val: float, cfg: dict) -> bool:
    """分配パターン（売り候補）: RSI≧70 かつ 出来高急増の陰線。"""
    if df.empty:
        return False
    vol_ratio = cfg["wyckoff"]["distribution"]["volume_ratio"]
    lookback = cfg["wyckoff"]["lookback"]
    if len(df) < lookback:
        return False
    vol_ma = calculate_volume_ma(df["Volume"], lookback).iloc[-1]
    last = df.iloc[-1]
    overbought = rsi_val >= cfg["rsi"]["overbought"]
    vol_spike = bool(last["Volume"] >= vol_ma * vol_ratio)
    bearish = bool(last["Close"] < last["Open"])
    return overbought and vol_spike and bearish
