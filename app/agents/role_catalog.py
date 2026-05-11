"""EDHREC-derived commander role and typal catalog."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
THEMES_CSV = ROOT / "docs" / "edhdeckthemes.csv"
TYPALS_CSV = ROOT / "docs" / "edhdecktypals.csv"


@dataclass(frozen=True)
class RoleCatalogEntry:
    name: str
    kind: str
    deck_count: int
    description: str
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        return data


THEME_DESCRIPTIONS = {
    "Tokens": "Builds a wide board with creature or artifact tokens, then uses payoffs, sacrifice outlets, or anthem effects.",
    "+1/+1 Counters": "Grows creatures with +1/+1 counters and rewards counter placement, doubling, or proliferation.",
    "Artifacts": "Uses artifacts as the main engine for mana, card advantage, sacrifice value, or combat payoffs.",
    "Combo": "Assembles compact card interactions that create a decisive loop, lock, or win condition.",
    "Lifegain": "Turns repeated life gain into cards, counters, tokens, damage, or long-game inevitability.",
    "Aggro": "Applies fast creature pressure and uses combat boosts, haste, or evasion to end games.",
    "Spellslinger": "Rewards casting instants, sorceries, or many noncreature spells in a turn.",
    "Aristocrats": "Sacrifices creatures for value and wins through death triggers, drain effects, or recursion.",
    "Reanimator": "Fills the graveyard and returns high-impact creatures or permanents to the battlefield.",
    "Lands Matter": "Rewards land drops, extra lands, land recursion, or lands entering the battlefield.",
    "Treasure": "Creates and spends Treasure tokens as ramp, artifact fuel, sacrifice fodder, or payoff triggers.",
    "Equipment": "Uses Equipment to build resilient attackers, commander-damage threats, or combat-value engines.",
    "Control": "Wins by surviving with interaction, card advantage, and resilient finishers.",
    "Burn": "Uses repeatable or amplified damage effects to pressure creatures and players.",
    "Enchantress": "Rewards enchantments and Auras with card draw, mana, protection, or board growth.",
    "Ramp": "Accelerates mana production to cast larger threats or activate expensive abilities ahead of curve.",
    "Mill": "Puts cards from libraries into graveyards as a primary engine or win condition.",
    "Voltron": "Focuses resources on one major attacker, often the commander, to win through combat damage.",
    "Midrange": "Combines efficient threats, interaction, and value engines for a flexible long game.",
    "Sacrifice": "Uses sacrifice outlets and expendable permanents to generate value or trigger payoffs.",
    "Wheels": "Refills or disrupts hands with mass discard-and-draw effects and rewards the churn.",
    "cEDH": "Optimizes for fast mana, tutors, compact wins, and high-interaction competitive Commander play.",
    "Auras": "Builds around Aura synergies, enchanted creatures, protection, or enchantment payoffs.",
    "Legends": "Rewards legendary permanents, historic spells, or commander-centric legendary synergies.",
    "Blink": "Exiles and returns permanents to reuse enter-the-battlefield effects or protect key pieces.",
    "Discard": "Forces or rewards discarding cards, often converting discarded cards into value or pressure.",
    "Clones": "Copies creatures or permanents to multiply the best threats and enter-the-battlefield effects.",
    "Graveyard": "Uses the graveyard as a resource for casting, recursion, value, or win conditions.",
    "Landfall": "Triggers payoffs whenever lands enter the battlefield.",
    "Flying": "Builds around evasive flying creatures, aerial anthems, and combat-damage rewards.",
    "Infect": "Uses poison counters, toxic, infect, or proliferate to win through poison pressure.",
    "Card Draw": "Turns drawing cards into an engine, payoff, or core resource advantage plan.",
    "Big Mana": "Creates large amounts of mana for high-impact spells, X spells, or expensive activations.",
    "Stax": "Uses restrictive permanents to slow opponents while the deck breaks parity.",
    "Group Slug": "Pressures every opponent with repeated damage or life-loss effects.",
    "Storm": "Casts many spells in one turn and converts spell count into a win or overwhelming value.",
    "Planeswalkers": "Builds around planeswalker value, protection, loyalty abilities, and proliferate.",
    "Extra Combats": "Creates additional combat steps and rewards attack triggers or combat damage.",
    "Group Hug": "Gives resources to the table while converting that generosity into leverage or a win.",
    "Vehicles": "Builds around Vehicle and crew synergies.",
    "Self-Mill": "Mills itself to stock the graveyard for recursion, casting, or graveyard payoffs.",
    "Cascade": "Uses cascade or discover to generate free spells and chain value.",
    "Energy": "Generates and spends energy counters as a dedicated resource engine.",
    "Ninjutsu": "Uses evasive attackers and ninjutsu to create combat-damage value.",
    "Lifedrain": "Drains opponents while gaining life or triggering life-change payoffs.",
    "ETB": "Reuses or multiplies enter-the-battlefield abilities for value.",
    "Proliferate": "Adds counters to permanents or players to scale poison, loyalty, or creature counters.",
    "Food": "Creates and uses Food tokens for life, sacrifice, artifact, or value synergies.",
    "Mutate": "Stacks mutate creatures to build one threat with repeated mutate triggers.",
    "Politics": "Uses table incentives, voting, deals, and opponent choices to gain advantage.",
    "Activated Abilities": "Rewards activating abilities or reduces, copies, or amplifies those activations.",
    "Flashback": "Casts spells from the graveyard for added value and spell density.",
    "Madness": "Uses discard outlets to cast cards for madness costs and gain tempo or value.",
    "Scry": "Uses scrying as a setup engine and rewards repeated top-deck selection.",
    "Shrines": "Builds around Shrines and scaling enchantment payoffs.",
}

THEME_ALIASES = {
    "+1/+1 Counters": ("Counters", "Counters Matter"),
    "Artifacts": ("Artifact Matters",),
    "Combo": ("Storm / Combo",),
    "Enchantress": ("Enchantments",),
    "Lands Matter": ("Landfall",),
    "Voltron": ("Combat Damage",),
    "Reanimator": ("Graveyard Engine",),
    "Ramp": ("Ramp Engine",),
    "Card Draw": ("Card Draw Engine",),
    "Treasure": ("Treasures",),
    "Spellslinger": ("Instants and Sorceries",),
}


def _read_catalog_csv(path: Path) -> list[tuple[str, int]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            (row["Name"].strip(), int(row["Decks"]))
            for row in csv.DictReader(handle)
            if row.get("Name") and row.get("Decks")
        ]


def _theme_description(name: str) -> str:
    return THEME_DESCRIPTIONS.get(name, f"Builds around {name} synergies as the deck's main plan.")


def _typal_description(name: str) -> str:
    return f"Creature-type synergy deck built around {name}."


@lru_cache(maxsize=1)
def get_role_catalog_entries() -> tuple[RoleCatalogEntry, ...]:
    entries: list[RoleCatalogEntry] = []
    for name, deck_count in _read_catalog_csv(THEMES_CSV):
        entries.append(
            RoleCatalogEntry(
                name=name,
                kind="theme",
                deck_count=deck_count,
                description=_theme_description(name),
                aliases=THEME_ALIASES.get(name, ()),
            )
        )
    for name, deck_count in _read_catalog_csv(TYPALS_CSV):
        singular = name[:-1] if name.endswith("s") else name
        aliases = (singular,) if singular != name else ()
        entries.append(
            RoleCatalogEntry(
                name=name,
                kind="typal",
                deck_count=deck_count,
                description=_typal_description(name),
                aliases=aliases,
            )
        )
    return tuple(entries)


def get_role_catalog() -> dict:
    themes = []
    typals = []
    for entry in get_role_catalog_entries():
        target = themes if entry.kind == "theme" else typals
        target.append(entry.to_dict())
    themes.sort(key=lambda e: e["deck_count"], reverse=True)
    typals.sort(key=lambda e: e["deck_count"], reverse=True)
    return {"themes": themes, "typals": typals}


def get_role_metadata(name: str) -> dict | None:
    normalized = name.strip().lower()
    for entry in get_role_catalog_entries():
        names = (entry.name, *entry.aliases)
        if any(candidate.lower() == normalized for candidate in names):
            return entry.to_dict()
    return None
