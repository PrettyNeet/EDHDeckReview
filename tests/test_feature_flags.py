"""Tests for runtime feature flags."""

from unittest.mock import patch

from app import main
from app.models.card import CardEntry, ValidationResult
from app.models.card import BracketAssessment


def _entry():
    return CardEntry(quantity=1, raw_name="Sol Ring", name="Sol Ring", found=True)


def test_ai_review_feature_flag_prevents_provider_call(monkeypatch):
    monkeypatch.setenv("FEATURE_AI_REVIEW_ENABLED", "false")

    with (
        patch("app.main.parse_decklist_text", return_value=[_entry()]),
        patch("app.main.validate", return_value=ValidationResult()),
        patch("app.main.synergy_agent.analyze", return_value={
            "synergy_clusters": [],
            "mana_curve": {},
            "type_breakdown": {},
            "role_breakdown": {},
            "missing_staples": [],
            "warnings": [],
            "avg_cmc": 0,
        }),
        patch("app.main.bracket_agent.evaluate", return_value=BracketAssessment(bracket=1, label="Exhibition")),
        patch("app.main.plan_analyzer.analyze_plan", return_value={}),
        patch("app.main.ai_advisor.generate_review") as generate_review,
    ):
        result = main._run_review(
            "1 Sol Ring",
            commander_hint=None,
            intended_bracket=None,
            skip_ai=False,
        )

    generate_review.assert_not_called()
    assert result["features"]["ai_review"] is False
    assert result["ai_disabled_reason"] == "AI review is disabled by feature flag."
