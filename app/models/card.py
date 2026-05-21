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
    """Full analysis result for a decklist. Mirrors the shape of the /review API response."""
    # Identity
    commander: Optional[str] = None
    partner: Optional[str] = None
    color_identity: list[str] = field(default_factory=list)

    # Card counts
    card_count: int = 0
    found_count: int = 0

    # Full card list
    cards: list[CardEntry] = field(default_factory=list)

    # Validation
    validation: Optional[ValidationResult] = None

    # Bracket
    bracket: Optional[BracketAssessment] = None
    intended_bracket: Optional[int] = None

    # Synergy analysis
    synergy_clusters: list[SynergyCluster] = field(default_factory=list)
    mana_curve: dict[str, int] = field(default_factory=dict)
    type_breakdown: dict[str, int] = field(default_factory=dict)
    role_breakdown: dict[str, int] = field(default_factory=dict)
    missing_staples: list[str] = field(default_factory=list)
    synergy_warnings: list[str] = field(default_factory=list)
    avg_cmc: float = 0.0

    # Plan framework (plan_analyzer.analyze_plan output)
    plan: Optional[dict] = None
    target_commander_roles: list[str] = field(default_factory=list)

    # EDHREC
    edhrec: Optional[dict] = None
    creativity: Optional[dict] = None

    # Budget
    budget: Optional[dict] = None

    # AI
    ai_summary: Optional[str] = None
    ai_suggestions: list[str] = field(default_factory=list)
    ai_available: bool = False
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None

    # Request tracking
    request_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "commander": self.commander,
            "partner": self.partner,
            "color_identity": self.color_identity,
            "card_count": self.card_count,
            "found_count": self.found_count,
            "cards": [c.to_dict() for c in self.cards],
            "validation": self.validation.to_dict() if self.validation else None,
            "bracket": self.bracket.to_dict() if self.bracket else None,
            "intended_bracket": self.intended_bracket,
            "synergy_clusters": [s.to_dict() for s in self.synergy_clusters],
            "mana_curve": self.mana_curve,
            "type_breakdown": self.type_breakdown,
            "role_breakdown": self.role_breakdown,
            "missing_staples": self.missing_staples,
            "synergy_warnings": self.synergy_warnings,
            "avg_cmc": self.avg_cmc,
            "plan": self.plan,
            "target_commander_roles": self.target_commander_roles,
            "edhrec": self.edhrec,
            "creativity": self.creativity,
            "budget": self.budget,
            "ai_summary": self.ai_summary,
            "ai_suggestions": self.ai_suggestions,
            "ai_available": self.ai_available,
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model,
            "request_id": self.request_id,
        }
