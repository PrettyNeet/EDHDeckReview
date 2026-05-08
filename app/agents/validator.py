"""
Validator agent — enforces Commander format rules:
  • Exactly 100 cards (including commander)
  • Singleton (1 copy max, except basic lands and "any number" cards)
  • Every non-commander card's color identity must be a subset of the
    commander's color identity
  • All cards must be legal in Commander format
  • Commander must be a Legendary Creature (or have "can be your commander")
  • Partner / Friends Forever support
Reference: https://mtgcommander.net/index.php/rules/
"""

from collections import Counter
from app.models.card import CardEntry, ValidationResult

BASIC_LAND_NAMES = {
    "Plains", "Island", "Swamp", "Mountain", "Forest",
    "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
    "Snow-Covered Mountain", "Snow-Covered Forest",
    "Wastes",
}

ANY_NUMBER_PHRASE = "a deck can have any number of cards named"

# Some sets that are banned in Commander (not exhaustive — Scryfall legality covers most)
BANNED_CARDS = {
    "Ancestral Recall", "Balance", "Biorhythm", "Black Lotus", "Braids, Cabal Minion",
    "Channel", "Coalition Victory", "Chaos Orb", "Emrakul, the Aeons Torn",
    "Erayo, Soratami Ascendant", "Falling Star", "Fastbond", "Flash",
    "Gifts Ungiven", "Golos, Tireless Pilgrim", "Griselbrand",
    "Hullbreacher", "Iona, Shield of Emeria", "Karakas", "Leovold, Emissary of Trest",
    "Library of Alexandria", "Limited Resources", "Lutri, the Spellchaser",
    "Mox Sapphire", "Mox Ruby", "Mox Pearl", "Mox Jet", "Mox Emerald",
    "Panoptic Mirror", "Paradox Engine", "Primeval Titan",
    "Prophet of Kruphix", "Recurring Nightmare", "Rofellos, Llanowar Emissary",
    "Sundering Titan", "Sway of the Stars", "Sylvan Primordial",
    "Time Stretch", "Time Vault", "Time Walk", "Tinker",
    "Tolarian Academy", "Trade Secrets", "Upheaval",
    "Worldfire", "Yawgmoth's Bargain",
}


def _has_partner(entry: CardEntry) -> bool:
    txt = entry.oracle_text or ""
    return "Partner" in (entry.keywords or []) or "partner" in txt.lower()


def _has_friends_forever(entry: CardEntry) -> bool:
    txt = entry.oracle_text or ""
    return "friends forever" in txt.lower()


def _has_partner_with(entry: CardEntry) -> str | None:
    """Return the named partner target, or None."""
    txt = entry.oracle_text or ""
    import re
    m = re.search(r"[Pp]artner with ([^\n(]+)", txt)
    return m.group(1).strip(" .") if m else None


def _is_any_number_card(entry: CardEntry) -> bool:
    txt = entry.oracle_text or ""
    return ANY_NUMBER_PHRASE in txt.lower()


def validate(entries: list[CardEntry]) -> ValidationResult:
    result = ValidationResult()

    # ── Separate commanders from the main deck ─────────────────────────
    commanders = [e for e in entries if e.is_commander]
    deck = [e for e in entries if not e.is_commander]

    # ── 1. Commander presence ──────────────────────────────────────────
    if not commanders:
        result.add_error(
            "No commander identified. Mark one Legendary Creature as the "
            "commander, or prefix a line with 'Commander: '."
        )
        return result  # can't continue without a commander

    if len(commanders) > 2:
        result.add_error(f"Too many commanders ({len(commanders)}). Max 2 with Partner.")

    # ── 2. Commander validity ──────────────────────────────────────────
    for cmd in commanders:
        if not cmd.found:
            result.add_error(f"Commander '{cmd.raw_name}' not found in Scryfall database.")
            continue
        if not cmd.can_be_commander:
            result.add_error(
                f"'{cmd.name}' cannot be a commander (not a Legendary Creature "
                "and doesn't have 'can be your commander')."
            )

    # ── 3. Partner validation ──────────────────────────────────────────
    if len(commanders) == 2:
        c1, c2 = commanders[0], commanders[1]
        pw1 = _has_partner_with(c1)
        pw2 = _has_partner_with(c2)
        ff1 = _has_friends_forever(c1)
        ff2 = _has_friends_forever(c2)
        p1 = _has_partner(c1)
        p2 = _has_partner(c2)

        valid_pair = False
        if pw1 and pw2 and c1.name == pw2 and c2.name == pw1:
            valid_pair = True
        elif ff1 and ff2:
            valid_pair = True
        elif p1 and p2 and not pw1 and not pw2:
            valid_pair = True

        if not valid_pair:
            result.add_error(
                f"'{c1.name}' and '{c2.name}' are not a valid Partner pair."
            )

    # ── 4. Commander color identity ────────────────────────────────────
    commander_ci = set()
    for cmd in commanders:
        commander_ci.update(cmd.color_identity)

    if not commander_ci:
        # Colorless commander (e.g. Karn, Silver Golem)
        result.add_warning(
            f"Commander(s) have no color identity — deck is colorless. "
            "Only colorless cards are allowed."
        )

    # ── 5. Card count ──────────────────────────────────────────────────
    total_count = sum(e.quantity for e in entries)
    if total_count != 100:
        result.add_error(
            f"Deck has {total_count} cards. Commander decks must have exactly 100."
        )

    # ── 6. Singleton + color identity checks ──────────────────────────
    name_counts: Counter = Counter()
    for entry in entries:
        canonical = (entry.name or entry.raw_name).strip()
        name_counts[canonical] += entry.quantity

    for entry in deck:
        if not entry.found:
            result.add_warning(f"Card not found, skipping checks: '{entry.raw_name}'")
            continue

        canonical = (entry.name or entry.raw_name).strip()

        # Singleton check (basic lands and "any number" cards are exempt)
        if entry.is_basic_land or canonical in BASIC_LAND_NAMES or _is_any_number_card(entry):
            pass
        elif name_counts[canonical] > 1:
            result.add_error(
                f"'{canonical}' appears {name_counts[canonical]}× — Commander is a "
                "singleton format (only 1 copy allowed)."
            )

        # Color identity check
        card_ci = set(entry.color_identity)
        if not card_ci.issubset(commander_ci):
            illegal_colors = card_ci - commander_ci
            result.add_error(
                f"'{canonical}' has color identity {sorted(card_ci)} which includes "
                f"{sorted(illegal_colors)} — outside your commander's identity {sorted(commander_ci)}."
            )

        # Legality check (use Scryfall's commander legality)
        legality = (entry.legalities or {}).get("commander", "unknown")
        if legality == "banned":
            result.add_error(f"'{canonical}' is banned in Commander format.")
        elif legality == "not_legal":
            result.add_error(f"'{canonical}' is not legal in Commander format.")
        elif legality == "unknown":
            result.add_warning(f"Could not verify legality of '{canonical}'.")

        # Extra ban-list check (covers recent bans not yet in Scryfall data)
        if canonical in BANNED_CARDS:
            if not any(f"'{canonical}' is banned" in e for e in result.errors):
                result.add_error(f"'{canonical}' is on the Commander ban list.")

    return result


def get_commander_color_identity(entries: list[CardEntry]) -> list[str]:
    ci = set()
    for e in entries:
        if e.is_commander:
            ci.update(e.color_identity)
    return sorted(ci)
