"""Tests for non-blocking action logging."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from app import analytics
from app.auth import AuthUser


def test_log_event_noops_when_disabled(monkeypatch):
    monkeypatch.setenv("ACTION_LOGGING_ENABLED", "false")

    with patch("urllib.request.urlopen") as urlopen:
        analytics.log_event("deck_review_submitted")

    urlopen.assert_not_called()


def test_log_event_posts_expected_payload(monkeypatch):
    monkeypatch.setenv("ACTION_LOGGING_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        analytics.log_event(
            "deck_review_submitted",
            user=AuthUser(id="user-id", email="user@example.com"),
            request_id="rid",
            source="text",
            decklist_text="1 Sol Ring\n",
            input_metadata={"line_count": 1},
        )

    assert captured["url"] == "https://example.supabase.co/rest/v1/user_action_logs"
    assert captured["timeout"] == 5
    assert captured["payload"]["event_type"] == "deck_review_submitted"
    assert captured["payload"]["user_email"] == "user@example.com"
    assert captured["payload"]["decklist_text"] == "1 Sol Ring\n"
    assert captured["payload"]["input_metadata"]["line_count"] == 1


def test_log_event_swallows_insert_failures(monkeypatch):
    monkeypatch.setenv("ACTION_LOGGING_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")

    with patch("urllib.request.urlopen", side_effect=OSError("network failed")):
        analytics.log_event("deck_review_submitted")


def test_decklist_stats_counts_text():
    assert analytics.decklist_stats("1 Sol Ring\n\n1 Island\n") == {
        "bytes": 21,
        "chars": 21,
        "line_count": 2,
    }
