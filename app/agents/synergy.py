"""
Synergy analyzer agent.
Performs rule-based analysis of a parsed deck to identify:
  • Mana curve profile
  • Card type breakdown
  • Functional role breakdown (ramp / draw / removal / threats / synergy / lands)
  • Thematic/mechanical synergy clusters
  • Missing staples for the commander's colors
"""

from __future__ import annotations
import re
from collections import defaultdict, Counter

from functools import lru_cache

from app.models.card import CardEntry, SynergyCluster
from app.agents.card_lookup import lookup_otags, get_cards_by_otag

# ─── Role detection ────────────────────────────────────────────────────────────

_OTAG_ROLE_MAP: dict[str, str] = {
    "board-wipe":         "boardwipes",
    "removal":            "removal",
    "exile-target":       "removal",
    "counterspell":       "removal",
    "tutor":              "tutors",
    "draw":               "draw",
    "catalog":            "draw",
    "play-from-top":      "draw",
    "ramp":               "ramp",
    "mana-rock":          "ramp",
    "mana-dork":          "ramp",
    "graveyard-matters":  "synergy",
    "tribal":             "synergy",
    "synergy-mill":       "synergy",
    "power-matters":      "synergy",
    "pp-counters-matter": "synergy",
}

_OTAG_ROLE_PRIORITY = ["boardwipes", "removal", "tutors", "draw", "ramp", "synergy"]

RAMP_KEYWORDS = re.compile(
    r"add \{[WUBRGC]\}|search your library for a.*land|"
    r"you may put.*land.*into play|"
    r"whenever.*tapped for mana|"
    r"treasure|"
    r"sol ring|rampant growth|cultivate|kodama|three visits|"
    r"nature's lore|farseek|sylvan scrying|harvest season",
    re.IGNORECASE,
)
RAMP_TYPES = re.compile(r"(Land|Artifact).*—.*Mana", re.IGNORECASE)

DRAW_KEYWORDS = re.compile(
    r"draw (a card|cards|two|three|\d+ card)|"
    r"draw equal to|"
    r"investigate|"
    r"impulse draw|"
    r"whenever.*draw",
    re.IGNORECASE,
)

REMOVAL_KEYWORDS = re.compile(
    r"destroy target|exile target|"
    r"return target.*to.*hand|"
    r"counter target spell|"
    r"target creature gets -\d+/-\d+.*until end of turn|"
    r"deals \d+ damage to target|"
    r"fights target|"
    r"sacrifice target",
    re.IGNORECASE,
)

BOARDWIPE_KEYWORDS = re.compile(
    r"destroy all|exile all|"
    r"each (player|opponent).*sacrifices|"
    r"all creatures get -\d+/-\d+|"
    r"return all|"
    r"deals \d+ damage to each",
    re.IGNORECASE,
)

TUTOR_KEYWORDS = re.compile(
    r"search your library for (a|an|any|one|two|up to)",
    re.IGNORECASE,
)

# ─── Helper functions (must be defined before SYNERGY_RULES) ─────────────────

def _kw(e: CardEntry, kw: str) -> bool:
    return kw in (e.keywords or [])


def _txt(e: CardEntry, pattern: str) -> bool:
    return bool(re.search(pattern, e.oracle_text or "", re.IGNORECASE))


def _check_tribal(e: CardEntry) -> bool:
    txt = e.oracle_text or ""
    type_line = e.type_line or ""
    if re.search(r"other.*get \+\d+/\+\d+|each.*you control|creatures you control of the chosen type", txt, re.IGNORECASE):
        return True
    subtypes = re.findall(r"— (.+)$", type_line)
    if subtypes:
        creature_types = [s.strip() for s in subtypes[0].split() if s[0].isupper()]
        for ct in creature_types:
            if len(ct) > 2 and re.search(ct, txt, re.IGNORECASE):
                return True
    return False


# ─── Synergy cluster definitions ──────────────────────────────────────────────

SYNERGY_RULES: list[dict] = [
    # Keyword-based
    {
        "name": "Flying Matters",
        "check": lambda e: _kw(e, "Flying") or _txt(e, r"has flying|gain flying"),
        "description": "Cards that have or care about flying creatures.",
    },
    {
        "name": "Deathtouch Package",
        "check": lambda e: _kw(e, "Deathtouch") or _txt(e, r"deathtouch"),
        "description": "Deathtouch synergies — lethal on contact, great with first strike or ping effects.",
    },
    {
        "name": "Lifelink Synergy",
        "check": lambda e: _kw(e, "Lifelink") or _txt(e, r"lifelink|whenever you gain life"),
        "description": "Life gain and lifelink synergies.",
    },
    {
        "name": "Token Generation",
        "check": lambda e: _txt(e, r"create.*token|put.*token"),
        "description": "Cards that create tokens, enabling go-wide strategies.",
    },
    {
        "name": "Sacrifice Engine",
        "check": lambda e: _txt(e, r"sacrifice a |sacrifice another|when.*this creature dies|when.*is put into a graveyard"),
        "description": "Sacrifice synergies — turn deaths into value.",
    },
    {
        "name": "Graveyard Recursion",
        "check": lambda e: _txt(e, r"return.*from.*graveyard|from your graveyard to|reanimate|unearth"),
        "description": "Recursion pieces that rebuy cards from the graveyard.",
    },
    {
        "name": "Counter Manipulation",
        "check": lambda e: _txt(e, r"\+1/\+1 counter|proliferate|put.*counter"),
        "description": "+1/+1 counter synergies and proliferate effects.",
    },
    {
        "name": "Enchantress Package",
        "check": lambda e: "Enchantment" in (e.type_line or "") or _txt(e, r"whenever you (cast|play) an enchantment|enchantress"),
        "description": "Enchantment-matters cards.",
    },
    {
        "name": "Artifact Synergy",
        "check": lambda e: "Artifact" in (e.type_line or "") or _txt(e, r"whenever.*artifact (enters|comes into play)|artifact creature"),
        "description": "Artifact-matters synergies.",
    },
    {
        "name": "Spellslinger",
        "check": lambda e: _txt(e, r"whenever you cast (an instant|a sorcery|a spell)|magecraft|storm"),
        "description": "Instants-and-sorceries matter — rewards casting spells.",
    },
    {
        "name": "Landfall",
        "check": lambda e: _txt(e, r"landfall|whenever a land enters the battlefield under your control"),
        "description": "Landfall triggers reward playing lands each turn.",
    },
    {
        "name": "Tribal Synergy",
        "check": _check_tribal,
        "description": "Tribal lord effects or creature-type synergies.",
    },
    {
        "name": "Copy / Clone Effects",
        "check": lambda e: _txt(e, r"copy target|copies of|create a (token that's a copy|copy of)"),
        "description": "Copy and clone effects for value multiplication.",
    },
    {
        "name": "Blink / Flicker",
        "check": lambda e: _txt(e, r"exile.*return.*to the battlefield|blink|flicker"),
        "description": "Blink effects that re-trigger ETB abilities.",
    },
    {
        "name": "Extra Turns / Combat",
        "check": lambda e: _txt(e, r"take an extra turn|additional turn|additional combat|untap all"),
        "description": "Extra turn or combat effects — powerful tempo plays.",
    },
    {
        "name": "Storm / Combo Enabler",
        "check": lambda e: _txt(e, r"\bstorm\b|when you cast your second spell|each time you cast"),
        "description": "Storm or chained-spell combo pieces.",
    },
    {
        "name": "Commander Damage",
        "check": lambda e: _txt(e, r"commander|whenever.*deals combat damage") and e.is_creature,
        "description": "Cards that leverage commander damage as a win condition.",
    },
    {
        "name": "Mana Doubling",
        "check": lambda e: _txt(e, r"double the mana|add.*for each|whenever.*tapped for mana.*add"),
        "description": "Mana doublers that enable explosive turns.",
    },
    {
        "name": "Card Draw Engine",
        "check": lambda e: _txt(e, r"draw.*equal|draw.*each turn|whenever.*draw"),
        "description": "Sustained card draw engines.",
    },
    {
        "name": "Stax / Taxing Effects",
        "check": lambda e: _txt(e, r"spells cost.*more|can't untap|skip.*untap|opponents can't"),
        "description": "Stax and taxing effects that slow opponents.",
    },
]



# ─── Missing staples ──────────────────────────────────────────────────────────

# Otag tags to query per color when surfacing missing staples.
# Cards are filtered by commander color identity and sorted by game_changer desc, cmc asc.
_COLOR_STAPLE_OTAGS: dict[str, list[str]] = {
    "W": ["removal", "board-wipe"],
    "U": ["counterspell", "draw"],
    "B": ["tutor", "removal"],
    "R": ["removal", "ramp"],
    "G": ["ramp", "mana-dork"],
    "C": ["mana-rock"],   # colorless mana rocks only
}

_MAX_STAPLES_PER_COLOR = 6


@lru_cache(maxsize=64)
def _staples_for_color(color: str, ci_tuple: tuple[str, ...]) -> list[str]:
    """Return up to _MAX_STAPLES_PER_COLOR staple suggestions for one color, cached per (color, ci)."""
    tags = _COLOR_STAPLE_OTAGS.get(color, [])
    if not tags:
        return []
    if color == "C":
        cards = [
            c for c in get_cards_by_otag(tags, commander_ci=None, max_results=60)
            if not c["color_identity"]
        ]
    else:
        cards = [
            c for c in get_cards_by_otag(tags, commander_ci=list(ci_tuple), max_results=60)
            if color in c["color_identity"]
        ]
    return [c["name"] for c in cards[:_MAX_STAPLES_PER_COLOR]]


def _cards_in_deck(entries: list[CardEntry]) -> set[str]:
    return {(e.name or "").lower() for e in entries}


# ─── Role classification (single primary role for overview chart) ─────────────
# Full multi-role assignment lives in plan_analyzer.assign_roles().
# This function keeps one label per card for the simple role bar chart.

def classify_role(entry: CardEntry) -> str:
    if entry.is_land:
        return "lands"

    otags = lookup_otags(entry.name or "")
    if otags:
        mapped = {_OTAG_ROLE_MAP[t] for t in otags if t in _OTAG_ROLE_MAP}
        for role in _OTAG_ROLE_PRIORITY:
            if role in mapped:
                return role

    txt = entry.oracle_text or ""
    type_line = entry.type_line or ""

    if BOARDWIPE_KEYWORDS.search(txt):
        return "boardwipes"
    if REMOVAL_KEYWORDS.search(txt):
        return "removal"
    if TUTOR_KEYWORDS.search(txt):
        return "tutors"
    if DRAW_KEYWORDS.search(txt):
        return "draw"
    if RAMP_KEYWORDS.search(txt) or "Mana" in type_line:
        return "ramp"
    if entry.is_creature and entry.power and entry.power.isdigit() and int(entry.power) >= 5:
        return "threats"
    return "synergy"


# ─── Main analysis function ───────────────────────────────────────────────────

def analyze(entries: list[CardEntry]) -> dict:
    """
    Returns a dict with:
      mana_curve, type_breakdown, role_breakdown,
      synergy_clusters, missing_staples, color_staple_warnings
    """
    non_land = [e for e in entries if not e.is_land and e.found]
    found = [e for e in entries if e.found]

    # ── Mana curve ────────────────────────────────────────────────────
    curve: Counter = Counter()
    for e in non_land:
        cmc = int(e.cmc) if e.cmc is not None else 0
        bucket = str(min(cmc, 7))  # 7+ lumped together
        curve[bucket] += e.quantity
    # Ensure all buckets exist
    mana_curve = {str(i): curve.get(str(i), 0) for i in range(8)}
    if curve.get("7", 0):
        mana_curve["7+"] = curve["7"]
        del mana_curve["7"]

    # ── Type breakdown ────────────────────────────────────────────────
    type_map = {
        "Creatures": lambda e: e.is_creature,
        "Instants": lambda e: e.is_instant,
        "Sorceries": lambda e: e.is_sorcery,
        "Artifacts": lambda e: e.is_artifact and not e.is_creature,
        "Enchantments": lambda e: e.is_enchantment and not e.is_creature,
        "Planeswalkers": lambda e: e.is_planeswalker,
        "Lands": lambda e: e.is_land,
    }
    type_breakdown = {}
    for label, fn in type_map.items():
        type_breakdown[label] = sum(e.quantity for e in found if fn(e))

    # ── Role breakdown ────────────────────────────────────────────────
    role_counts: Counter = Counter()
    for e in found:
        role = classify_role(e)
        role_counts[role] += e.quantity
    role_breakdown = dict(role_counts)

    # ── Synergy clusters ──────────────────────────────────────────────
    clusters: list[SynergyCluster] = []
    for rule in SYNERGY_RULES:
        matching = [e.name for e in found if rule["check"](e)]
        if len(matching) >= 3:
            strength = "high" if len(matching) >= 8 else ("medium" if len(matching) >= 5 else "low")
            clusters.append(SynergyCluster(
                name=rule["name"],
                description=rule["description"],
                cards=matching,
                strength=strength,
            ))

    # Sort by strength then card count
    strength_order = {"high": 0, "medium": 1, "low": 2}
    clusters.sort(key=lambda c: (strength_order[c.strength], -len(c.cards)))

    # ── Missing staples ───────────────────────────────────────────────
    commander_ci = set()
    for e in entries:
        if e.is_commander:
            commander_ci.update(e.color_identity)

    deck_names = _cards_in_deck(found)
    missing_staples: list[str] = []
    ci_tuple = tuple(sorted(commander_ci))

    for card in _staples_for_color("C", ()):
        if card.lower() not in deck_names:
            missing_staples.append(card)

    for color in commander_ci:
        for card in _staples_for_color(color, ci_tuple):
            if card.lower() not in deck_names and card not in missing_staples:
                missing_staples.append(card)

    # ── Ramp / Draw ratio warnings ────────────────────────────────────
    warnings: list[str] = []
    ramp_count = role_breakdown.get("ramp", 0)
    draw_count = role_breakdown.get("draw", 0)
    removal_count = role_breakdown.get("removal", 0) + role_breakdown.get("boardwipes", 0)
    land_count = role_breakdown.get("lands", 0)

    # Targets from RoughDeckPlan.csv framework
    if ramp_count < 10:
        warnings.append(
            f"Low ramp count ({ramp_count}). Framework target is 12 (minimum 10). "
            "Remember: ramp after a missed land drop doesn't count."
        )
    if draw_count < 10:
        warnings.append(
            f"Low card draw count ({draw_count}). Framework target is 12 — never go below this. "
            "Card advantage gets you your synergy and engine pieces."
        )
    if removal_count < 10:
        warnings.append(
            f"Low interaction ({removal_count} removal + boardwipes). "
            "Framework targets 12 removal + 6 mass disruption (minimum 2 boardwipes)."
        )
    if land_count < 35:
        warnings.append(
            f"Low land count ({land_count}). Framework target is 38 — enough to hit land drops "
            "consistently through turn 6 with 7 draw effects and mulligans."
        )
    elif land_count > 40:
        warnings.append(
            f"High land count ({land_count}). Consider dropping to 38 and adding ramp/draw."
        )

    avg_cmc = (
        sum((e.cmc or 0) * e.quantity for e in non_land) / max(sum(e.quantity for e in non_land), 1)
    )

    return {
        "mana_curve": mana_curve,
        "type_breakdown": type_breakdown,
        "role_breakdown": role_breakdown,
        "synergy_clusters": [c.to_dict() for c in clusters],
        "missing_staples": missing_staples[:12],
        "warnings": warnings,
        "avg_cmc": round(avg_cmc, 2),
    }
