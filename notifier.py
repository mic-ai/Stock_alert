import logging
import time
import requests


def send_line_message(
    message: str,
    channel_access_token: str,
    user_id: str,
    api_endpoint: str,
    retry_count: int,
) -> bool:
    """LINE Messaging API push messageで送信。失敗時はretry_count回リトライ。"""
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json",
    }
    body = {"to": user_id, "messages": [{"type": "text", "text": message}]}
    for attempt in range(retry_count + 1):
        try:
            resp = requests.post(api_endpoint, headers=headers, json=body, timeout=10)
            if resp.status_code == 200:
                return True
            logging.warning(
                f"[notifier] LINE送信失敗 (attempt {attempt + 1}): "
                f"{resp.status_code} {resp.text}"
            )
        except Exception as e:
            logging.warning(f"[notifier] LINE送信例外 (attempt {attempt + 1}): {e}")
        if attempt < retry_count:
            time.sleep(2)
    return False


def format_buy_alert(candidates: list[dict], date_str: str) -> str:
    lines = [f"【買い候補アラート】{date_str}"]
    for c in candidates:
        patterns_str = "/".join(c["patterns"])
        lines.append(f"▶ {c['ticker']} {c['name']} [{c['market']}]")
        lines.append(f"  RSI: {c['rsi']} | パターン: {patterns_str}")
    return "\n".join(lines)


def format_sell_alert(candidates: list[dict], date_str: str) -> str:
    lines = [f"【売り候補アラート】{date_str}"]
    for c in candidates:
        reason_str = "/".join(c["reason"])
        lines.append(f"▶ {c['ticker']} {c['name']} [{c['market']}]")
        lines.append(f"  RSI: {c['rsi']} | 理由: {reason_str}")
    return "\n".join(lines)
