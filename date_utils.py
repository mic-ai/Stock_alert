from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def today_jst() -> str:
    """JST基準の当日日付をYYYY-MM-DD形式で返す。"""
    return datetime.now(JST).strftime("%Y-%m-%d")
