import logging
import smtplib
import time
from email.mime.text import MIMEText


def send_email(
    message: str,
    subject: str,
    gmail_user: str,
    gmail_app_password: str,
    to_address: str,
    retry_count: int,
) -> bool:
    """GmailのSMTPでメール送信。失敗時はretry_count回リトライ。"""
    msg = MIMEText(message, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_address
    for attempt in range(retry_count + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
                smtp.login(gmail_user, gmail_app_password)
                smtp.send_message(msg)
            return True
        except Exception as e:
            logging.warning(f"[notifier] メール送信失敗 (attempt {attempt + 1}): {e}")
        if attempt < retry_count:
            time.sleep(2)
    return False


def format_buy_alert(candidates: list[dict], date_str: str) -> tuple[str, str]:
    """(subject, body) を返す。"""
    subject = f"【買い候補アラート】{date_str} ({len(candidates)}銘柄)"
    lines = [f"【買い候補アラート】{date_str}\n"]
    for c in candidates:
        patterns_str = "/".join(c["patterns"])
        lines.append(f"▶ {c['ticker']} {c['name']} [{c['market']}]")
        lines.append(f"  RSI: {c['rsi']} | パターン: {patterns_str}\n")
    return subject, "\n".join(lines)


def format_sell_alert(candidates: list[dict], date_str: str) -> tuple[str, str]:
    """(subject, body) を返す。"""
    subject = f"【売り候補アラート】{date_str} ({len(candidates)}銘柄)"
    lines = [f"【売り候補アラート】{date_str}\n"]
    for c in candidates:
        reason_str = "/".join(c["reason"])
        lines.append(f"▶ {c['ticker']} {c['name']} [{c['market']}]")
        lines.append(f"  RSI: {c['rsi']} | 理由: {reason_str}\n")
    return subject, "\n".join(lines)


def _format_hit_rate_block(label: str, agg: dict) -> list[str]:
    lines = [f"■ {label}"]
    if agg["hit_rate"] is None:
        lines.append("  評価データなし\n")
        return lines
    hit_rate_pct = agg["hit_rate"] * 100
    lines.append(
        f"  的中率: {hit_rate_pct:.1f}% ({agg['hit_count']}/{agg['total']}件、不的中{agg['miss_count']}件)\n"
    )
    return lines


def format_evaluation_summary(agg: dict, date_str: str) -> tuple[str, str]:
    """的中率評価バッチの日次サマリー(subject, body)を返す。
    agg = {"buy": {...}, "sell": {...}} （prediction_tracker.aggregate_hit_rateの戻り値）。
    """
    subject = f"【日次レポート】的中率サマリー ({date_str})"
    lines = [f"【的中率サマリー】{date_str}\n"]
    lines += _format_hit_rate_block("買い候補", agg["buy"])
    lines += _format_hit_rate_block("売り候補", agg["sell"])
    return subject, "\n".join(lines)
