"""
Moxfield deck importer.
Converts a Moxfield deck URL to plain-text decklist format via the Moxfield API.
"""

import re
import json
import urllib.request
from typing import Optional

MOXFIELD_API = "https://api.moxfield.com/v2/decks/all"
_USER_AGENT = "MTG-DeckReview/1.0 (local tool)"


def extract_deck_id(url: str) -> Optional[str]:
    """Extract the deck ID from a Moxfield URL."""
    match = re.search(r"moxfield\.com/decks/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def fetch_deck(deck_id: str) -> dict:
    """Fetch raw deck JSON from the Moxfield API."""
    url = f"{MOXFIELD_API}/{deck_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_decklist_text(data: dict) -> tuple[str, Optional[str]]:
    """
    Convert Moxfield deck JSON to plain-text decklist format compatible with
    the deck_parser (Commander: tags + qty name lines).
    Returns (decklist_text, primary_commander_name_or_None).
    """
    lines: list[str] = []
    commander_name: Optional[str] = None

    for name, _entry in (data.get("commanders") or {}).items():
        # Tag line so the parser sets is_commander; quantity line so the card
        # appears in the entries list and gets Scryfall-enriched.
        lines.append(f"Commander: {name}")
        lines.append(f"1 {name}")
        if commander_name is None:
            commander_name = name

    for name, entry in (data.get("companions") or {}).items():
        qty = entry.get("quantity", 1)
        lines.append(f"{qty} {name}")

    for name, entry in (data.get("mainboard") or {}).items():
        qty = entry.get("quantity", 1)
        lines.append(f"{qty} {name}")

    return "\n".join(lines), commander_name


def fetch_and_convert(url: str) -> dict:
    """
    Full pipeline: Moxfield URL -> deck ID -> API -> decklist text.
    Returns {"text", "commander", "deck_name", "error"}.
    """
    deck_id = extract_deck_id(url)
    if not deck_id:
        return {
            "error": "Could not parse a Moxfield deck ID from the URL.",
            "text": None,
            "commander": None,
            "deck_name": None,
        }

    try:
        data = fetch_deck(deck_id)
    except Exception as exc:
        return {
            "error": str(exc),
            "text": None,
            "commander": None,
            "deck_name": None,
        }

    text, commander = to_decklist_text(data)
    return {
        "error": None,
        "text": text,
        "commander": commander,
        "deck_name": data.get("name"),
    }
