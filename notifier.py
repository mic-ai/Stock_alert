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


def format_panic_alert_block(status: dict) -> str:
    """市場パニック警戒ブロック(日次レポート本文への追記用)。"""
    lines = [
        "\n【市場パニック警戒】",
        f"パニックスコア: {status['market_panic_score']:.1f} / 閾値: {status['alert_score_threshold']:.1f}",
        f"クロス市場デカップリング: {'該当' if status['decoupling'] else '非該当'}",
        f"セリングクライマックスbreadth: {status['climax_breadth']:.1%}",
        f"RSI売られ過ぎbreadth: {status['rsi_breadth']:.1%}",
        f"連続急落: {'該当' if status['consecutive_decline'] else '非該当'}",
        "※自動検知シグナルです。必ずご自身で状況を確認してください。\n",
    ]
    return "\n".join(lines)


def format_bottom_candidate_block(status: dict) -> str:
    """底打ち候補シグナルブロック(日次レポート本文への追記用)。"""
    lines = [
        "\n【底打ち候補シグナル】",
        "直近のパニックがピークアウトし、沈静化の兆候が見られます。",
        f"セリングクライマックスbreadth: {status['climax_breadth']:.1%}",
        f"watchlist平均騰落率: {status['jp_avg_return']:.2%}",
        "※あくまで候補シグナルです。Wyckoff法のAR/STの形成状況もあわせてご確認ください。\n",
    ]
    return "\n".join(lines)


def format_low_reliability_note(status: dict) -> str:
    """パニック判定の元データが不足している場合の注記ブロック。"""
    return (
        "\n【注意】市場パニック判定の信頼性低下\n"
        f"watchlist {status['n_total']}銘柄中 {status['n_fetched']}銘柄のみ取得成功のため、"
        "上記のパニック判定は参考程度としてください。\n"
    )


def format_evaluation_summary(agg: dict, date_str: str) -> tuple[str, str]:
    """的中率評価バッチの日次サマリー(subject, body)を返す。
    agg = {"buy": {...}, "sell": {...}} （prediction_tracker.aggregate_hit_rateの戻り値）。
    """
    subject = f"【日次レポート】的中率サマリー ({date_str})"
    lines = [f"【的中率サマリー】{date_str}\n"]
    lines += _format_hit_rate_block("買い候補", agg["buy"])
    lines += _format_hit_rate_block("売り候補", agg["sell"])
    return subject, "\n".join(lines)
