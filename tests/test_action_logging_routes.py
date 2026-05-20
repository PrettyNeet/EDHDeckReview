"""Route-level tests for action logging hooks."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import main
from app.auth import AuthUser


def _request():
    return SimpleNamespace(
        url=SimpleNamespace(path="/api/moxfield", query=""),
        method="GET",
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )


def _analysis():
    return {
        "commander": "Sol Ring",
        "partner": None,
        "color_identity": [],
        "card_count": 1,
        "found_count": 1,
        "validation": {"valid": True, "errors": [], "warnings": []},
        "bracket": {"bracket": 1},
        "budget": None,
        "edhrec": {"available": False},
        "creativity": None,
        "ai_available": False,
        "ai_provider": None,
        "ai_model": None,
        "features": {"ai_review": False},
        "request_id": "rid",
        "_diagnostics": {"timings": {"total_ms": 1}},
    }


@pytest.mark.anyio
async def test_moxfield_success_logs_requested_and_completed():
    events = []
    with (
        patch("app.main.analytics.log_event", side_effect=lambda event_type, **kwargs: events.append((event_type, kwargs))),
        patch("app.main.analytics.new_request_id", return_value="rid"),
        patch("app.main.moxfield_agent.extract_deck_id", return_value="deck123"),
        patch("app.main.moxfield_agent.fetch_and_convert", return_value={
            "error": None,
            "text": "1 Sol Ring\n",
            "commander": "Sol Ring",
            "deck_name": "Test Deck",
        }),
    ):
        result = await main.import_moxfield(
            "https://moxfield.com/decks/deck123",
            _request(),
            AuthUser(id="u1", email="user@example.com"),
        )

    assert result["request_id"] == "rid"
    assert [event for event, _ in events] == ["moxfield_import_requested", "moxfield_import_completed"]
    assert events[1][1]["decklist_text"] == "1 Sol Ring\n"


@pytest.mark.anyio
async def test_moxfield_failure_logs_failed_event():
    events = []
    with (
        patch("app.main.analytics.log_event", side_effect=lambda event_type, **kwargs: events.append((event_type, kwargs))),
        patch("app.main.analytics.new_request_id", return_value="rid"),
        patch("app.main.moxfield_agent.extract_deck_id", return_value="deck123"),
        patch("app.main.moxfield_agent.fetch_and_convert", return_value={
            "error": "No deck",
            "text": None,
            "commander": None,
            "deck_name": None,
        }),
    ):
        with pytest.raises(HTTPException):
            await main.import_moxfield(
                "https://moxfield.com/decks/deck123",
                _request(),
                AuthUser(id="u1", email="user@example.com"),
            )

    assert [event for event, _ in events] == ["moxfield_import_requested", "moxfield_import_failed"]


@pytest.mark.anyio
async def test_review_text_success_logs_submitted_and_completed():
    events = []
    with (
        patch("app.main.analytics.log_event", side_effect=lambda event_type, **kwargs: events.append((event_type, kwargs))),
        patch("app.main.analytics.new_request_id", return_value="rid"),
        patch("app.main._run_review", return_value=_analysis()),
    ):
        response = await main.review_from_text(
            _request(),
            decklist="1 Sol Ring\n",
            commander=None,
            intended_bracket=None,
            skip_ai=True,
            ai_provider=None,
            ai_model=None,
            commander_roles=None,
            budget_tier=None,
            _user=AuthUser(id="u1", email="user@example.com"),
        )

    assert response.status_code == 200
    assert [event for event, _ in events] == ["deck_review_submitted", "deck_review_completed"]
    assert events[0][1]["decklist_text"] == "1 Sol Ring\n"
    assert events[1][1]["result_summary"]["commander"] == "Sol Ring"


@pytest.mark.anyio
async def test_review_text_failure_logs_failed_event():
    events = []
    with (
        patch("app.main.analytics.log_event", side_effect=lambda event_type, **kwargs: events.append((event_type, kwargs))),
        patch("app.main.analytics.new_request_id", return_value="rid"),
        patch("app.main._run_review", side_effect=HTTPException(status_code=400, detail="bad deck")),
    ):
        with pytest.raises(HTTPException):
            await main.review_from_text(
                _request(),
                decklist="bad",
                commander=None,
                intended_bracket=None,
                skip_ai=True,
                ai_provider=None,
                ai_model=None,
                commander_roles=None,
                budget_tier=None,
                _user=AuthUser(id="u1", email="user@example.com"),
            )

    assert [event for event, _ in events] == ["deck_review_submitted", "deck_review_failed"]
    assert events[1][1]["error"]["status_code"] == 400
