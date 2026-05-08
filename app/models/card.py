"""Card and deck data models."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


COLORS = {"W", "U", "B", "R", "G", "C"}
COLOR_NAMES = {"W": "White", "U": "Blue", "B": "Black", "R": "Red", "G": "Green", "C": "Colorless"}


@dataclass
class CardEntry:
    """A single card slot in a decklist, enriched with Scryfall data."""
    # From decklist file
    quantity: int
    raw_name: str          # name as it appeared in the .txt file
    is_commander: bool = False

    # From Scryfall
    name: Optional[str] = None
    cmc: Optional[float] = None
    color_identity: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    defense: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    mana_cost: Optional[str] = None
    oracle_text: Optional[str] = None
    power: Optional[str] = None
    toughness: Optional[str] = None
    type_line: Optional[str] = None
    legalities: dict = field(default_factory=dict)
    game_changer: bool = False
    rarity: Optional[str] = None
    scryfall_uri: Optional[str] = None

    # Lookup status
    found: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_basic_land(self) -> bool:
        t = self.type_line or ""
        return "Basic Land" in t or "Basic Snow Land" in t

    @property
    def is_creature(self) -> bool:
        return "Creature" in (self.type_line or "")

    @property
    def is_land(self) -> bool:
        return "Land" in (self.type_line or "")

    @property
    def is_artifact(self) -> bool:
        return "Artifact" in (self.type_line or "")

    @property
    def is_enchantment(self) -> bool:
        return "Enchantment" in (self.type_line or "")

    @property
    def is_instant(self) -> bool:
        return "Instant" in (self.type_line or "")

    @property
    def is_sorcery(self) -> bool:
        return "Sorcery" in (self.type_line or "")

    @property
    def is_planeswalker(self) -> bool:
        return "Planeswalker" in (self.type_line or "")

    @property
    def is_legendary(self) -> bool:
        return "Legendary" in (self.type_line or "")

    @property
    def can_be_commander(self) -> bool:
        t = self.type_line or ""
        txt = self.oracle_text or ""
        legalities = self.legalities or {}
        if "commander" not in legalities or legalities["commander"] != "legal":
            return False
        if "commander" in legalities and legalities["commander"] == "legal":
            return True
        return False


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SynergyCluster:
    name: str
    description: str
    cards: list[str] = field(default_factory=list)
    strength: str = "medium"   # low / medium / high

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BracketAssessment:
    bracket: int               # 1-5
    label: str
    reasoning: list[str] = field(default_factory=list)
    game_changer_count: int = 0
    game_changer_cards: list[str] = field(default_factory=list)
    fast_mana_count: int = 0
    combo_potential: str = "none"  # none / low / medium / high

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeckAnalysis:
    """Full analysis result for a decklist."""
    commander: Optional[str] = None
    partner: Optional[str] = None
    color_identity: list[str] = field(default_factory=list)
    card_count: int = 0
    cards: list[CardEntry] = field(default_factory=list)

    validation: Optional[ValidationResult] = None
    bracket: Optional[BracketAssessment] = None
    synergy_clusters: list[SynergyCluster] = field(default_factory=list)

    # Mana curve: cmc → count
    mana_curve: dict[str, int] = field(default_factory=dict)

    # Card type breakdown
    type_breakdown: dict[str, int] = field(default_factory=dict)

    # Role breakdown (ramp/draw/removal/threats/synergy/lands)
    role_breakdown: dict[str, int] = field(default_factory=dict)

    # AI suggestions
    ai_summary: Optional[str] = None
    ai_suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "commander": self.commander,
            "partner": self.partner,
            "color_identity": self.color_identity,
            "card_count": self.card_count,
            "cards": [c.to_dict() for c in self.cards],
            "validation": self.validation.to_dict() if self.validation else None,
            "bracket": self.bracket.to_dict() if self.bracket else None,
            "synergy_clusters": [s.to_dict() for s in self.synergy_clusters],
            "mana_curve": self.mana_curve,
            "type_breakdown": self.type_breakdown,
            "role_breakdown": self.role_breakdown,
            "ai_summary": self.ai_summary,
            "ai_suggestions": self.ai_suggestions,
        }
        return d
