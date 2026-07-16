import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
import pytest
from notifier import send_line_message, format_buy_alert, format_sell_alert

ENDPOINT = "https://api.line.me/v2/bot/message/push"


class TestFormatBuyAlert:
    def test_header_included(self):
        candidates = [{"ticker": "NVDA", "name": "NVIDIA", "rsi": 55.0,
                        "patterns": ["spring"], "sector": "semiconductor", "market": "US"}]
        msg = format_buy_alert(candidates, "2026-07-16")
        assert "【買い候補アラート】2026-07-16" in msg
        assert "NVDA" in msg
        assert "spring" in msg
        assert "RSI: 55.0" in msg

    def test_multiple_patterns(self):
        candidates = [{"ticker": "6857.T", "name": "アドバンテスト", "rsi": 42.0,
                        "patterns": ["spring", "choch"], "sector": "semiconductor", "market": "JP"}]
        msg = format_buy_alert(candidates, "2026-07-16")
        assert "spring/choch" in msg


class TestFormatSellAlert:
    def test_sell_alert_format(self):
        candidates = [{"ticker": "NVDA", "name": "NVIDIA", "rsi": 72.0,
                        "reason": ["業種下降トレンド"], "sector": "semiconductor", "market": "US"}]
        msg = format_sell_alert(candidates, "2026-07-16")
        assert "【売り候補アラート】2026-07-16" in msg
        assert "業種下降トレンド" in msg


class TestSendLineMessage:
    def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("notifier.requests.post", return_value=mock_resp) as mock_post:
            result = send_line_message("msg", "token", "uid", ENDPOINT, retry_count=1)
        assert result is True
        assert mock_post.call_count == 1

    def test_failure_then_retry_success(self):
        fail = MagicMock()
        fail.status_code = 500
        fail.text = "Internal Server Error"
        ok = MagicMock()
        ok.status_code = 200
        with patch("notifier.requests.post", side_effect=[fail, ok]) as mock_post:
            with patch("notifier.time.sleep"):
                result = send_line_message("msg", "token", "uid", ENDPOINT, retry_count=1)
        assert result is True
        assert mock_post.call_count == 2

    def test_all_attempts_fail(self):
        fail = MagicMock()
        fail.status_code = 429
        fail.text = "Too Many Requests"
        with patch("notifier.requests.post", return_value=fail):
            with patch("notifier.time.sleep"):
                result = send_line_message("msg", "token", "uid", ENDPOINT, retry_count=1)
        assert result is False
