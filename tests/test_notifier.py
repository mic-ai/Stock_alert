import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
import pytest
from notifier import send_email, format_buy_alert, format_sell_alert


class TestFormatBuyAlert:
    def test_header_included(self):
        candidates = [{"ticker": "NVDA", "name": "NVIDIA", "rsi": 55.0,
                        "patterns": ["spring"], "sector": "semiconductor", "market": "US"}]
        subject, body = format_buy_alert(candidates, "2026-07-16")
        assert "買い候補アラート" in subject
        assert "2026-07-16" in subject
        assert "NVDA" in body
        assert "spring" in body
        assert "RSI: 55.0" in body

    def test_multiple_patterns(self):
        candidates = [{"ticker": "6857.T", "name": "アドバンテスト", "rsi": 42.0,
                        "patterns": ["spring", "choch"], "sector": "semiconductor", "market": "JP"}]
        subject, body = format_buy_alert(candidates, "2026-07-16")
        assert "spring/choch" in body


class TestFormatSellAlert:
    def test_sell_alert_format(self):
        candidates = [{"ticker": "NVDA", "name": "NVIDIA", "rsi": 72.0,
                        "reason": ["業種下降トレンド"], "sector": "semiconductor", "market": "US"}]
        subject, body = format_sell_alert(candidates, "2026-07-16")
        assert "売り候補アラート" in subject
        assert "業種下降トレンド" in body


class TestSendEmail:
    def test_success(self):
        mock_smtp = MagicMock()
        with patch("notifier.smtplib.SMTP_SSL", return_value=mock_smtp.__enter__.return_value):
            with patch("smtplib.SMTP_SSL") as mock_cls:
                mock_cls.return_value.__enter__ = lambda s: mock_cls.return_value
                mock_cls.return_value.__exit__ = MagicMock(return_value=False)
                result = send_email(
                    "body", "subject", "user@gmail.com", "apppass",
                    "to@example.com", retry_count=0
                )
        assert result is True

    def test_failure_then_retry_success(self):
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            ctx = MagicMock()
            if call_count["n"] == 1:
                ctx.__enter__ = MagicMock(side_effect=Exception("connection error"))
            else:
                ctx.__enter__ = MagicMock(return_value=MagicMock())
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        with patch("notifier.smtplib.SMTP_SSL", side_effect=side_effect):
            with patch("notifier.time.sleep"):
                result = send_email(
                    "body", "subject", "user@gmail.com", "apppass",
                    "to@example.com", retry_count=1
                )
        assert result is True
        assert call_count["n"] == 2

    def test_all_attempts_fail(self):
        with patch("notifier.smtplib.SMTP_SSL", side_effect=Exception("always fails")):
            with patch("notifier.time.sleep"):
                result = send_email(
                    "body", "subject", "user@gmail.com", "apppass",
                    "to@example.com", retry_count=1
                )
        assert result is False
