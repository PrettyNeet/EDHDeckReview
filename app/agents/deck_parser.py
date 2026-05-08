"""
Deck parser agent.
Reads a .txt decklist, resolves each card via the Scryfall index,
and returns a list of CardEntry objects ready for analysis.

Supported formats:
  1 Rhystic Study
  1x Sol Ring
  4 Mountain   (basic lands with qty > 1 are fine)
  // Comment lines or section headers are skipped
  Commander: Atraxa, Praetor's Voice  (optional explicit tag)
"""

import re
from pathlib import Path
from typing import Optional

from app.models.card import CardEntry
from app.agents.card_lookup import lookup

# Cards that Scryfall marks as able to have any number in a deck
ANY_NUMBER_TEXT = "a deck can have any number of cards named"

# Lines to skip
_SKIP_RE = re.compile(
    r"^\s*(?:"
    r"//.*|"              # // comments
    r"#.*|"              # # comments
    r"SB:.*|"            # sideboard markers (we ignore sideboard)
    r"Maybeboard.*|"
    r"Sideboard.*|"
    r"Commander.*:.*|"   # explicit Commander: tag (handled separately)
    r"\s*"               # blank lines
    r")\s*$",
    re.IGNORECASE,
)

_ENTRY_RE = re.compile(
    r"^\s*(?P<qty>\d+)[xX]?\s+(?P<name>.+?)\s*$"
)

_COMMANDER_TAG_RE = re.compile(
    r"^\s*commander\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE
)


def _parse_line(line: str) -> tuple[int, str] | None:
    """Return (qty, name) or None."""
    m = _ENTRY_RE.match(line.strip())
    if not m:
        return None
    return int(m.group("qty")), m.group("name").strip()


def parse_decklist_text(text: str, commander_hint: Optional[str] = None) -> list[CardEntry]:
    """
    Parse raw decklist text. Returns a list of CardEntry objects.
    The first Legendary Creature found (or explicit commander tag) is flagged
    as the commander.
    """
    entries: list[CardEntry] = []
    explicit_commanders: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Explicit commander tag
        ctag = _COMMANDER_TAG_RE.match(line)
        if ctag:
            explicit_commanders.append(ctag.group("name").strip())
            continue

        # Skip comment/section lines
        if _SKIP_RE.match(line):
            continue

        parsed = _parse_line(line)
        if not parsed:
            continue

        qty, name = parsed
        entries.append(CardEntry(quantity=qty, raw_name=name))

    if not entries:
        return entries

    # Enrich with Scryfall data
    for entry in entries:
        card = lookup(entry.raw_name)
        if card:
            entry.found = True
            entry.name = card["name"]
            entry.cmc = card.get("cmc")
            entry.color_identity = card.get("color_identity") or []
            entry.colors = card.get("colors") or []
            entry.defense = card.get("defense")
            entry.keywords = card.get("keywords") or []
            entry.mana_cost = card.get("mana_cost")
            entry.oracle_text = card.get("oracle_text")
            entry.power = card.get("power")
            entry.toughness = card.get("toughness")
            entry.type_line = card.get("type_line")
            entry.legalities = card.get("legalities") or {}
            entry.game_changer = bool(card.get("game_changer"))
            entry.rarity = card.get("rarity")
            entry.scryfall_uri = card.get("scryfall_uri")
        else:
            entry.found = False
            entry.error = f"Card not found in Scryfall database: '{entry.raw_name}'"

    # Flag commanders
    if commander_hint:
        explicit_commanders.insert(0, commander_hint)

    if explicit_commanders:
        for ec in explicit_commanders:
            for entry in entries:
                if entry.name and entry.name.lower() == ec.lower():
                    entry.is_commander = True
    else:
        # Auto-detect: first legendary creature or "can be your commander" card
        for entry in entries:
            if entry.found and entry.can_be_commander:
                entry.is_commander = True
                break

    return entries


def parse_decklist_file(path: str | Path, commander_hint: Optional[str] = None) -> list[CardEntry]:
    """Read a decklist .txt file and parse it."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_decklist_text(text, commander_hint=commander_hint)


def get_commanders(entries: list[CardEntry]) -> list[CardEntry]:
    return [e for e in entries if e.is_commander]


def get_non_commander_entries(entries: list[CardEntry]) -> list[CardEntry]:
    return [e for e in entries if not e.is_commander]
