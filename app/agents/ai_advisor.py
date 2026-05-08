"""
AI Advisor agent — uses a configured model provider to generate:
  • A natural-language deck summary
  • Specific card-swap suggestions informed by bracket, synergy clusters,
    missing staples, and validation issues
  • Reasoning that is aware of the player's intended bracket

Supports Anthropic/OpenAI keys and local Ollama models from the environment
(or .env file).
Falls back gracefully if no configured provider is available.
"""

from __future__ import annotations
import os
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from app.agents.card_lookup import lookup

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

ANTHROPIC_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL = "gpt-4o-mini"
OLLAMA_MODEL = "llama3.1"
OLLAMA_BASE_URL = "http://localhost:11434"
SYSTEM_PROMPT = (
    "You are an expert MTG Commander deck coach. "
    "Be specific, concise, and practical. "
    "Never make up cards — only suggest real Magic cards."
)

_SUGGESTED_ADD_PATTERNS = [
    re.compile(r"(?:→|->)\s*Add:\s*([^\n.;—]+)", re.IGNORECASE),
    re.compile(r"\bAdd:\s*([^\n.;—]+)", re.IGNORECASE),
    re.compile(r"\bwith\s+([^\n.;—]+)", re.IGNORECASE),
]
_SUGGESTED_CUT_PATTERNS = [
    re.compile(r"\bCut:\s*([^\n.;—]+)", re.IGNORECASE),
    re.compile(r"\bRemove:\s*([^\n.;—]+)", re.IGNORECASE),
]

_client: Optional["anthropic.Anthropic"] = None
_ENV_LOADED = False


def _strip_env_value(value: str) -> str:
    """Parse simple .env values, including quoted strings and inline comments."""
    value = value.strip()
    if not value:
        return ""
    if value[0] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    return value.split(" #", 1)[0].strip()


def _load_env_file() -> None:
    """Load project-root .env when the app was not started through run.py."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    root = Path(__file__).resolve().parents[2]
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), _strip_env_value(value))

    _ENV_LOADED = True


def _get_anthropic_client() -> Optional["anthropic.Anthropic"]:
    global _client
    _load_env_file()
    if not _ANTHROPIC_AVAILABLE:
        return None
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _normalize_provider(provider: Optional[str]) -> str:
    _load_env_file()
    requested = (provider or os.environ.get("AI_PROVIDER") or "auto").strip().lower()
    aliases = {
        "claude": "anthropic",
        "anthropic": "anthropic",
        "openai": "openai",
        "gpt": "openai",
        "ollama": "ollama",
        "local": "ollama",
        "auto": "auto",
    }
    return aliases.get(requested, "auto")


def _provider_available(provider: str) -> bool:
    _load_env_file()
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY")) and _ANTHROPIC_AVAILABLE
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "ollama":
        return True
    return False


def _select_provider(provider: Optional[str]) -> Optional[str]:
    requested = _normalize_provider(provider)
    if requested in ("anthropic", "openai", "ollama"):
        return requested if _provider_available(requested) else None
    if _provider_available("anthropic"):
        return "anthropic"
    if _provider_available("openai"):
        return "openai"
    if os.environ.get("OLLAMA_MODEL") and _provider_available("ollama"):
        return "ollama"
    return None


def _select_model(provider: str, model: Optional[str]) -> str:
    _load_env_file()
    if model:
        return model.strip()
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL)
    if provider == "openai":
        return os.environ.get("OPENAI_MODEL", OPENAI_MODEL)
    return os.environ.get("OLLAMA_MODEL", OLLAMA_MODEL)


def _ollama_base_url() -> str:
    _load_env_file()
    return os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL).rstrip("/")


def _build_prompt(analysis_data: dict, intended_bracket: Optional[int]) -> str:
    """Construct the system+user prompt for the AI review."""

    commander = analysis_data.get("commander", "Unknown")
    partner = analysis_data.get("partner")
    color_identity = analysis_data.get("color_identity", [])
    bracket_data = analysis_data.get("bracket") or {}
    computed_bracket = bracket_data.get("bracket", "?")
    validation = analysis_data.get("validation") or {}
    errors = validation.get("errors", [])
    warnings = validation.get("warnings", [])
    synergy_clusters = analysis_data.get("synergy_clusters", [])
    role_breakdown = analysis_data.get("role_breakdown", {})
    missing_staples = analysis_data.get("missing_staples", [])
    avg_cmc = analysis_data.get("avg_cmc", 0)
    type_breakdown = analysis_data.get("type_breakdown", {})
    card_count = analysis_data.get("card_count", 0)
    deck_list = analysis_data.get("cards", [])

    # Plan framework data
    plan = analysis_data.get("plan") or {}
    cmd_roles = plan.get("commander_roles", [])
    detected_roles = plan.get("detected_commander_roles", [])
    role_source = plan.get("commander_roles_source", "detected")
    _focus_raw = plan.get("commander_focus_advice") or {}
    if isinstance(_focus_raw, str):
        focus_advice = _focus_raw
    else:
        focus_advice = _focus_raw.get("text", "")
        _cards = _focus_raw.get("suggested_cards", [])
        if _cards:
            focus_advice += " Suggested: " + ", ".join(c["name"] for c in _cards[:4]) + "."
    coverage = (plan.get("coverage") or {}).get("categories", {})
    ptv = plan.get("path_to_victory") or {}
    playtest = plan.get("playtest_simulation") or {}
    mulligan = plan.get("mulligan_guide") or {}
    curve_eval = plan.get("curve_evaluation") or {}
    budget = analysis_data.get("budget") or {}
    budget_label = budget.get("label") or "No Limit"
    budget_cap = budget.get("max_card_price")

    # Coverage summary string
    coverage_lines = []
    for cat, data in coverage.items():
        status_icon = "✓" if data["status"] == "ok" else ("~" if data["status"] == "close" else "⚠")
        coverage_lines.append(
            f"  {status_icon} {cat}: {data['actual']}/{data['target']} ({data['delta']:+d})"
        )
    coverage_str = "\n".join(coverage_lines) or "  Not available."

    # Cards list (non-commander, names only for brevity)
    cards = analysis_data.get("cards", [])
    non_cmd_cards = [
        c["name"] for c in cards
        if not c.get("is_commander") and c.get("found") and c.get("name")
    ]

    commander_display = commander
    if partner:
        commander_display += f" + {partner}"

    bracket_note = ""
    if intended_bracket:
        if intended_bracket != computed_bracket:
            bracket_note = (
                f"The player declared Bracket {intended_bracket} but the system assessed "
                f"Bracket {computed_bracket}. Address this mismatch in your suggestions."
            )
        else:
            bracket_note = f"Bracket {intended_bracket} confirmed by analysis."

    budget_note = (
        f"Budget target: {budget_label}. Avoid recommending single cards above ${budget_cap:.2f} "
        "based on TCGplayer price when possible."
        if isinstance(budget_cap, (int, float))
        else "Budget target: No strict cap."
    )

    synergy_summary = "\n".join(
        f"  - {c['name']} ({c['strength']}): {c['description']} "
        f"[{len(c['cards'])} cards: {', '.join(c['cards'][:5])}{'...' if len(c['cards'])>5 else ''}]"
        for c in synergy_clusters[:8]
    ) or "  None detected."

    playtest_summary = "\n".join(
        f"  - {a}" for a in playtest.get("assessments", [])
    ) or "  Not available."

    prompt = f"""You are an expert Magic: The Gathering Commander deck advisor using the RoughDeckPlan framework.
Analyze the following deck and provide:
Use exactly these markdown section headers:
**Deck Summary**
**Card Suggestions**
**Coverage Gaps**
**Power-Level Assessment**

In **Card Suggestions**, provide specific, actionable card suggestions. Each suggestion should be one numbered item with the cut/add swap and its explanation together, using this shape:
1. Cut: [Card X] → Add: [Card Y] — with the reasoning for the swap. If relevant, note if the card is a staple or a strong synergy piece.

In **Coverage Gaps**, address any category gaps from the plan framework coverage.
In **Power-Level Assessment**, close with the deck's power level, curve, and playgroup fit.

═══ DECK OVERVIEW ═══
Commander: {commander_display}
Color Identity: {', '.join(color_identity) or 'Colorless'}
Commander Roles: {', '.join(cmd_roles) or 'None set'}{' (user target override)' if role_source == 'user' else ''}
Detected Commander Roles: {', '.join(detected_roles)}
Total Cards: {card_count}
Average CMC: {avg_cmc}
Computed Bracket: {computed_bracket}
{bracket_note}
{budget_note}
decklist: {deck_list}

═══ PLAN FRAMEWORK COVERAGE (targets: Lands 38 / Card Adv 12 / Ramp 12 / Removal 12 / Mass Disruption 6 / Plan 30) ═══
{coverage_str}

═══ COMMANDER ROLE & FOCUS ADVICE ═══
{focus_advice}

═══ PATH TO VICTORY ═══
Confidence: {ptv.get('confidence', '?')}
{ptv.get('summary', '')}
Low-CMC payoffs: {', '.join(ptv.get('low_cmc_payoffs', [])) or 'None'}

═══ SIMULATED 5-TURN PLAYTEST ═══
{playtest_summary}

═══ MULLIGAN ENGINE PIECES ═══
Engine pieces (keep in hand): {', '.join(mulligan.get('engine_pieces', [])[:6]) or 'None'}
Early ramp (prioritize): {', '.join(mulligan.get('early_ramp_pieces', [])[:6]) or 'None'}

═══ SYNERGY CLUSTERS ═══
{synergy_summary}

═══ CURVE NOTES ═══
{'; '.join(curve_eval.get('notes', [])) or 'Curve looks balanced.'}

═══ VALIDATION ISSUES ═══
Errors: {errors or 'None'}
Warnings: {warnings or 'None'}

═══ MISSING STAPLES FLAGGED ═══
{', '.join(missing_staples) or 'None'}

═══ FULL CARD LIST ═══
{', '.join(non_cmd_cards)}

─────────────────────────────────────────────
Tone: Direct, knowledgeable, helpful.
Focus suggestions on Bracket {intended_bracket or computed_bracket}.
Respect the stated budget target. If a premium staple would exceed the cap, prefer a cheaper alternative that fills a similar role.
Prioritize fixes for underfilled framework categories, then reinforce the strongest synergy clusters.
Consider card overlap — suggest cards that fill 2+ categories simultaneously.
If the deck has validation errors, note them but don't dwell on them.
Once you have your suggestions, check to make sure they are real Magic cards. If you aren't sure about a card, don't suggest it. Check your final suggestions for any that might be too obscure or narrow in appeal, and if so, replace them with more broadly useful cards.
Check the final list of suggestions against the card list to avoid suggesting cards that are already included. If they are already in the deck list, review that suggestion and replace it with another card that addresses the same issue but isn't already in the deck.
Only suggest cards that are Commander-legal and inside the commander's color identity.
"""
    return prompt


def generate_review(
    analysis_data: dict,
    intended_bracket: Optional[int] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Call the configured model provider to generate a natural-language deck review.
    Returns {"summary": str, "suggestions": [str], "available": bool}.
    Falls back to rule-based text if no configured provider is available.
    """
    selected_provider = _select_provider(provider)

    if not selected_provider:
        return {
            "summary": _fallback_summary(analysis_data),
            "suggestions": _fallback_suggestions(analysis_data),
            "available": False,
            "provider": _normalize_provider(provider),
            "model": None,
        }

    prompt = _build_prompt(analysis_data, intended_bracket)
    selected_model = _select_model(selected_provider, model)

    try:
        if selected_provider == "anthropic":
            text = _generate_anthropic(prompt, selected_model)
        elif selected_provider == "openai":
            text = _generate_openai(prompt, selected_model)
        else:
            text = _generate_ollama(prompt, selected_model)
        summary, suggestions = _parse_response(text)
        suggestions = _sanitize_suggestions(suggestions, analysis_data)
        return {
            "summary": summary,
            "suggestions": suggestions,
            "full_response": text,
            "available": True,
            "provider": selected_provider,
            "model": selected_model,
        }
    except Exception as exc:
        return {
            "summary": _fallback_summary(analysis_data),
            "suggestions": _fallback_suggestions(analysis_data),
            "error": str(exc),
            "available": False,
            "provider": selected_provider,
            "model": selected_model,
        }


def _generate_anthropic(prompt: str, model: str) -> str:
    client = _get_anthropic_client()
    if not client:
        raise RuntimeError("Anthropic provider is not configured.")

    response = client.messages.create(
        model=model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _generate_openai(prompt: str, model: str) -> str:
    _load_env_file()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI provider is not configured.")

    payload = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": prompt,
        "max_output_tokens": 1200,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc

    text = data.get("output_text")
    if text:
        return text.strip()

    parts: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])

    if not parts:
        raise RuntimeError("OpenAI response did not include text output.")
    return "\n".join(parts).strip()


def _generate_ollama(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    url = f"{_ollama_base_url()}/api/chat"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Ollama at {url}: {exc.reason}") from exc

    text = (data.get("message") or {}).get("content")
    if text:
        return text.strip()
    raise RuntimeError("Ollama response did not include message content.")


def _parse_response(text: str) -> tuple[str, list[str]]:
    """Split the AI response into a summary paragraph and suggestion bullets."""
    text = re.sub(r"\s*(\*{0,2}(?:deck\s+summary|card\s+suggestions?|coverage\s+gaps?|power-level\s+assessment)\*{0,2}:?)", r"\n\1\n", text, flags=re.IGNORECASE)
    lines = text.splitlines()
    summary_lines = []
    suggestions = []
    current_suggestion = ""
    in_suggestions = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if re.match(r"^\*{0,2}(?:card\s+)?suggestions?\*{0,2}:?$", stripped, re.IGNORECASE):
            in_suggestions = True
            continue
        if re.match(r"^\*{0,2}(?:deck\s+summary)\*{0,2}:?$", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\*{0,2}(?:coverage\s+gaps?|power-level\s+assessment)\*{0,2}:?$", stripped, re.IGNORECASE):
            if current_suggestion:
                suggestions.append(current_suggestion.strip())
                current_suggestion = ""
            break

        is_suggestion_start = re.match(r"^(?:[-•]\s*)?(?:Cut|Add|Replace|Swap|Remove|Include|Try|Consider|→|->|\d+[\.\)])", stripped, re.IGNORECASE)
        if is_suggestion_start:
            in_suggestions = True
            if current_suggestion:
                suggestions.append(current_suggestion.strip())
            current_suggestion = stripped
            continue

        if in_suggestions:
            # Treat non-numbered/non-cut lines as the reasoning for the previous suggestion.
            if current_suggestion:
                current_suggestion = f"{current_suggestion} {stripped}"
            else:
                current_suggestion = stripped
        else:
            summary_lines.append(stripped)

    if current_suggestion:
        suggestions.append(current_suggestion.strip())

    summary = " ".join(summary_lines[:5])  # first few lines as summary
    return summary, suggestions[:10]


def _clean_card_candidate(raw: str) -> str:
    candidate = re.sub(r"[*_`\[\]]", "", str(raw or ""))
    candidate = re.split(r"\s+\b(?:because|for|to|if|while)\b", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
    candidate = re.split(r"\s+\(", candidate, maxsplit=1)[0]
    candidate = candidate.strip(" .:-—–")
    return candidate


def _extract_candidate_names(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    names: list[str] = []
    for pattern in patterns:
        for match in pattern.findall(text):
            cleaned = _clean_card_candidate(match)
            if cleaned:
                names.append(cleaned)
    return names


def _lookup_budget_price(card_data: dict) -> Optional[float]:
    prices = card_data.get("prices") or {}
    value = prices.get("usd") or prices.get("usd_foil")
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, 2) if parsed > 0 else None


def _validate_suggested_add(
    card_name: str,
    analysis_data: dict,
    deck_names_lower: set[str],
) -> tuple[Optional[str], Optional[str]]:
    card_data = lookup(card_name)
    if not card_data:
        return None, "not found in Scryfall bulk data"

    canonical = card_data.get("name") or card_name
    if canonical.lower() in deck_names_lower:
        return None, "already in deck"

    legality = (card_data.get("legalities") or {}).get("commander", "unknown")
    if legality not in ("legal", "restricted"):
        return None, "not Commander-legal"

    commander_colors = set(analysis_data.get("color_identity") or [])
    card_colors = set(card_data.get("color_identity") or [])
    if commander_colors and not card_colors.issubset(commander_colors):
        return None, "outside commander color identity"

    budget = analysis_data.get("budget") or {}
    budget_cap = budget.get("max_card_price")
    if isinstance(budget_cap, (int, float)):
        price = _lookup_budget_price(card_data)
        if price is not None and price > budget_cap:
            return None, "over budget cap"

    return canonical, None


def _validate_cut_targets(cut_names: list[str], deck_names_lower: set[str]) -> bool:
    if not cut_names:
        return True
    return any(name.lower() in deck_names_lower for name in cut_names)


def _sanitize_suggestions(suggestions: list[str], analysis_data: dict) -> list[str]:
    deck_names_lower = {
        (card.get("name") or card.get("raw_name") or "").strip().lower()
        for card in (analysis_data.get("cards") or [])
        if card.get("name") or card.get("raw_name")
    }
    sanitized: list[str] = []
    added_cards_seen: set[str] = set()

    for suggestion in suggestions:
        add_candidates = _extract_candidate_names(suggestion, _SUGGESTED_ADD_PATTERNS)
        cut_candidates = _extract_candidate_names(suggestion, _SUGGESTED_CUT_PATTERNS)

        if add_candidates and not _validate_cut_targets(cut_candidates, deck_names_lower):
            continue

        chosen_add = None
        chosen_raw = None
        for candidate in add_candidates:
            canonical, _reason = _validate_suggested_add(candidate, analysis_data, deck_names_lower)
            if canonical and canonical.lower() not in added_cards_seen:
                chosen_add = canonical
                chosen_raw = candidate
                break

        if add_candidates and not chosen_add:
            continue

        cleaned = suggestion
        if chosen_add and chosen_raw and chosen_add != chosen_raw:
            cleaned = re.sub(re.escape(chosen_raw), chosen_add, cleaned, count=1, flags=re.IGNORECASE)
            added_cards_seen.add(chosen_add.lower())

        sanitized.append(cleaned)

    if sanitized:
        return sanitized[:10]
    return _fallback_suggestions(analysis_data)


# ─── Fallback (no API key) ────────────────────────────────────────────────────

def _fallback_summary(data: dict) -> str:
    commander = data.get("commander", "your commander")
    bracket = (data.get("bracket") or {}).get("label", "unknown bracket")
    clusters = data.get("synergy_clusters", [])
    top_theme = clusters[0]["name"] if clusters else "general value"
    return (
        f"This deck is built around {commander} and falls in the {bracket} range. "
        f"The primary synergy theme is '{top_theme}'. "
        "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or choose Ollama to enable model-powered suggestions."
    )


def _fallback_suggestions(data: dict) -> list[str]:
    suggestions = []
    missing = data.get("missing_staples", [])
    role = data.get("role_breakdown", {})
    budget = data.get("budget") or {}
    budget_cap = budget.get("max_card_price")
    budget_limited = isinstance(budget_cap, (int, float))

    if missing:
        suggestions.append(
            f"Consider adding format staples: {', '.join(missing[:4])}."
            + (" Favor lower-cost options that stay inside your budget target." if budget_limited else "")
        )
    if role.get("ramp", 0) < 8:
        suggestions.append(
            "Ramp is low — add more 1–3 mana ramp pieces that match your colors and curve."
        )
    if role.get("draw", 0) < 8:
        suggestions.append(
            "Card draw is low — add more efficient 2–4 mana draw engines that fit your commander and color identity."
        )
    if (role.get("removal", 0) + role.get("boardwipes", 0)) < 6:
        suggestions.append(
            "Interaction count is low — add more targeted removal and at least 1–2 board wipes that are legal in your colors."
        )

    errors = (data.get("validation") or {}).get("errors", [])
    for e in errors[:2]:
        suggestions.append(f"Fix: {e}")

    return suggestions or ["No specific suggestions — deck looks solid!"]
