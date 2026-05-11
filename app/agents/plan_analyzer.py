"""
Plan Analyzer — evaluates a deck against the RoughDeckPlan.csv framework.

Category targets:
  Lands              38  (can lower with consistent mana dorks/ramp)
  Card Advantage     12  (1 card → 1+n cards; never go below this)
  Ramp               12  (10 minimum; ramp after a missed land drop doesn't count)
  Removal            12  (targeted: 1 card removes 1 other card)
  Mass Disruption     6  (at least 2 board wipes; variety in what it handles matters)
  Plan Cards         30  (enablers + payoffs + enhancers)
  ─────────────────────
  Raw total         110  (~10 cards overlap → nets to 100 in a singleton deck)

Ideal non-land CMC distribution:
  CMC 0: 0   CMC 1: 9   CMC 2: 18  CMC 3: 15
  CMC 4: 10  CMC 5: 5   CMC 6: 5   CMC 7+: 5   (total = 67)

Key analyses:
  • Multi-role tagging       — cards can fill more than one category
  • Coverage summary         — actual vs target per category, overlap accounting
  • Commander role           — what the commander contributes, focus advice
  • CMC curve evaluation     — actual vs ideal distribution, sticky-point detection
  • Path to Victory          — is there a clear threat/win condition by turn 5?
  • Playtesting simulation   — expected category hits in 5–7 turn hands
  • Mulligan guide           — engine pieces needed to keep an opening hand
  • Sequencing guide         — ideal turn-by-turn deployment order
"""

from __future__ import annotations
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.models.card import CardEntry
from app.agents.card_lookup import lookup_otags
from app.agents.role_catalog import get_role_catalog_entries, get_role_metadata

# ─── Category targets ─────────────────────────────────────────────────────────

TARGETS = {
    "Lands":           38,
    "Card Advantage":  12,
    "Ramp":            12,
    "Removal":         12,
    "Mass Disruption":  6,
    "Plan Cards":      30,
}

IDEAL_CURVE = {0: 0, 1: 9, 2: 18, 3: 15, 4: 10, 5: 5, 6: 5, 7: 5}

# ─── Role detection patterns ──────────────────────────────────────────────────

_CARD_ADVANTAGE = re.compile(
    r"draw (a card|cards|two|three|\d+ card)|"
    r"draw equal to|"
    r"draw (X|\d+)|"
    r"investigate|"
    r"scry \d+.*draw|"
    r"whenever.*draw|"
    r"impulse draw|"
    r"look at the top|"
    r"reveal.*put.*hand|"
    r"create.*treasure|"
    r"whenever.*create a token.*draw",
    re.IGNORECASE,
)

_RAMP = re.compile(
    r"add \{[WUBRGC2]\}|"
    r"search your library for a.*land.*put.*(?:into play|onto the battlefield|into your hand)|"
    r"you may put.*land.*into play|"
    r"untap.*land|"
    r"whenever.*tapped for mana.*add|"
    r"treasure token|"
    r"add (one|two|three|\d+) mana|"
    r"add mana (equal|of any|in|of the colors)",
    re.IGNORECASE,
)
_RAMP_TYPES = re.compile(
    r"(Creature|Artifact).*—.*(Mana Dork|Elf|Dryad|Faerie|Bird)",
    re.IGNORECASE,
)

_REMOVAL = re.compile(
    r"destroy target|"
    r"exile target|"
    r"return target.*to.*(?:hand|library)|"
    r"counter target spell|"
    r"target creature gets -\d+/-\d+.*until end of turn|"
    r"deals \d+ damage to target|"
    r"target.*sacrifice|"
    r"fights? (?:another )?target|"
    r"tap target|"
    r"put target.*into.*graveyard",
    re.IGNORECASE,
)

_BOARDWIPE = re.compile(
    r"destroy all|"
    r"exile all|"
    r"each (player|opponent) sacrifices|"
    r"all creatures get -\d+/-\d+|"
    r"return all|"
    r"deals \d+ damage to (?:each|all)|"
    r"each creature|"
    r"sacrifice all",
    re.IGNORECASE,
)

_MASS_DISRUPTION_NONWIPE = re.compile(
    r"each opponent|"
    r"opponents can't|"
    r"players can't|"
    r"each player|"
    r"spells cost.*more|"
    r"skip.*untap",
    re.IGNORECASE,
)

_PLAN_ENABLER = re.compile(
    r"whenever|"
    r"at the beginning|"
    r"each time|"
    r"as long as|"
    r"enchant|"
    r"equipped creature|"
    r"fortify",
    re.IGNORECASE,
)

_PLAN_PAYOFF = re.compile(
    r"you win the game|"
    r"loses the game|"
    r"deal.*damage to.*player|"
    r"each opponent loses|"
    r"place.*poison counter|"
    r"infect|"
    r"commander damage|"
    r"storm count|"
    r"mill",
    re.IGNORECASE,
)

# Creatures with high power are usually plan payoffs/threats
_HIGH_POWER_THRESH = 5

_OTAG_CATEGORY_MAP: dict[str, list[str]] = {
    "ramp":               ["Ramp"],
    "mana-rock":          ["Ramp"],
    "mana-dork":          ["Ramp"],
    "draw":               ["Card Advantage"],
    "catalog":            ["Card Advantage"],
    "play-from-top":      ["Card Advantage"],
    "removal":            ["Removal"],
    "counterspell":       ["Removal"],
    "exile-target":       ["Removal"],
    "board-wipe":         ["Mass Disruption"],
    "tutor":              ["Plan Cards"],
    "graveyard-matters":  ["Plan Cards"],
    "tribal":             ["Plan Cards"],
    "synergy-mill":       ["Plan Cards"],
    "power-matters":      ["Plan Cards"],
    "pp-counters-matter": ["Plan Cards"],
}

# ─── Commander role detection ─────────────────────────────────────────────────

COMMANDER_ROLES = [
    ("Tokens", re.compile(r"create.*token|token.*copy|populate", re.IGNORECASE)),
    ("+1/+1 Counters", re.compile(r"\+1/\+1 counter|put.*counter.*creature|double.*counter", re.IGNORECASE)),
    ("Artifacts", re.compile(r"artifact", re.IGNORECASE)),
    ("Combo", re.compile(r"combo|infinite|you win the game|untap.*permanent|copy.*activated ability", re.IGNORECASE)),
    ("Lifegain", re.compile(r"gain.*life|lifelink|whenever.*life", re.IGNORECASE)),
    ("Aggro", re.compile(r"creatures you control.*attack|whenever.*attacks|haste|trample", re.IGNORECASE)),
    ("Spellslinger", re.compile(r"whenever you cast (an instant|a sorcery|a spell)|magecraft|instant or sorcery", re.IGNORECASE)),
    ("Aristocrats", re.compile(r"whenever.*creature.*dies|sacrifice a|whenever.*is put into a graveyard", re.IGNORECASE)),
    ("Reanimator", re.compile(r"return.*creature.*from.*graveyard|reanimate|put.*from.*graveyard.*battlefield", re.IGNORECASE)),
    ("Lands Matter", re.compile(r"land.*enters|landfall|play.*additional land|lands you control", re.IGNORECASE)),
    ("Treasure", re.compile(r"treasure", re.IGNORECASE)),
    ("Equipment", re.compile(r"equipment|equip|attached to|for each aura and equipment", re.IGNORECASE)),
    ("Control", re.compile(r"counter target|tap target|opponents can't|whenever.*counter|draw-go", re.IGNORECASE)),
    ("Burn", re.compile(r"deals? \d+ damage|noncombat damage|damage to each opponent", re.IGNORECASE)),
    ("Enchantress", re.compile(r"enchantment|aura|enchantress", re.IGNORECASE)),
    ("Ramp", re.compile(r"add \{|search.*land|untap.*land|mana of any color", re.IGNORECASE)),
    ("Mill", re.compile(r"mill|put.*library.*graveyard", re.IGNORECASE)),
    ("Voltron", re.compile(r"commander damage|attached|equipment|aura|gets \+\d+/\+\d+|double strike", re.IGNORECASE)),
    ("Midrange", re.compile(r"at the beginning.*upkeep|whenever.*enters|draw.*card|create.*token", re.IGNORECASE)),
    ("Sacrifice", re.compile(r"sacrifice", re.IGNORECASE)),
    ("Wheels", re.compile(r"discard.*hand.*draw|each player.*draw.*cards|wheel", re.IGNORECASE)),
    ("cEDH", re.compile(r"you win the game|thassa's oracle|demonic consultation|ad nauseam", re.IGNORECASE)),
    ("Auras", re.compile(r"aura|enchant creature|enchanted creature", re.IGNORECASE)),
    ("Legends", re.compile(r"legendary|historic", re.IGNORECASE)),
    ("Blink", re.compile(r"exile.*return.*battlefield|blink|flicker", re.IGNORECASE)),
    ("Discard", re.compile(r"discard", re.IGNORECASE)),
    ("Clones", re.compile(r"copy.*creature|token.*copy|becomes a copy|clone", re.IGNORECASE)),
    ("Graveyard", re.compile(r"graveyard|dies|escape|flashback|dredge|delirium", re.IGNORECASE)),
    ("Landfall", re.compile(r"landfall|land.*enters", re.IGNORECASE)),
    ("Flying", re.compile(r"flying|creatures.*with flying", re.IGNORECASE)),
    ("Infect", re.compile(r"infect|poison counter|toxic|proliferate", re.IGNORECASE)),
    ("Card Draw", re.compile(r"draw (a card|cards|\d+ card|equal)", re.IGNORECASE)),
    ("Birthing Pod", re.compile(r"sacrifice.*creature.*search.*library|mana value.*plus 1|pod", re.IGNORECASE)),
    ("Big Mana", re.compile(r"add.*for each|double.*mana|mana.*doesn't empty|x spell", re.IGNORECASE)),
    ("Stax", re.compile(r"can't untap|spells cost.*more|players can't|opponents can't|skip.*step", re.IGNORECASE)),
    ("Group Slug", re.compile(r"each opponent.*damage|whenever.*opponent.*loses life|players.*lose life", re.IGNORECASE)),
    ("Storm", re.compile(r"\bstorm\b|copy.*spell|second spell|cast.*spell.*turn", re.IGNORECASE)),
    ("Historic", re.compile(r"historic|artifact|legendary|saga", re.IGNORECASE)),
    ("Planeswalkers", re.compile(r"planeswalker|loyalty|proliferate", re.IGNORECASE)),
    ("Extra Combats", re.compile(r"additional combat|extra combat|untap.*attacking", re.IGNORECASE)),
    ("Chaos", re.compile(r"random|chaos|coin flip|at random", re.IGNORECASE)),
    ("Theft", re.compile(r"gain control|steal|exile.*you may cast", re.IGNORECASE)),
    ("Good Stuff", re.compile(r"draw.*card|create.*token|destroy target|exile target", re.IGNORECASE)),
    ("Cantrips", re.compile(r"draw a card|scry \d+.*draw|when you cast.*draw", re.IGNORECASE)),
    ("Group Hug", re.compile(r"each player.*draw|each player.*may|opponent.*draw.*card|add.*mana.*each player", re.IGNORECASE)),
    ("Vehicles", re.compile(r"vehicle|crew", re.IGNORECASE)),
    ("Self-Mill", re.compile(r"mill.*yourself|put.*top.*graveyard|surveil", re.IGNORECASE)),
    ("X Spells", re.compile(r"\{X\}|x is|mana value.*x", re.IGNORECASE)),
    ("Forced Combat", re.compile(r"attacks each combat|goad|must attack", re.IGNORECASE)),
    ("Exile", re.compile(r"exile", re.IGNORECASE)),
    ("Toughness Matters", re.compile(r"toughness|assigns combat damage equal to its toughness", re.IGNORECASE)),
    ("Topdeck", re.compile(r"top card|look at the top|play.*from the top|reveal.*top", re.IGNORECASE)),
    ("Commander Matters", re.compile(r"commander|command zone|commander tax", re.IGNORECASE)),
    ("Cascade", re.compile(r"cascade|discover", re.IGNORECASE)),
    ("Hatebears", re.compile(r"players can't|opponents can't|noncreature spells cost|activated abilities.*can't", re.IGNORECASE)),
    ("Energy", re.compile(r"energy counter|\{E\}", re.IGNORECASE)),
    ("-1/-1 Counters", re.compile(r"-1/-1 counter|wither|persist", re.IGNORECASE)),
    ("Ninjutsu", re.compile(r"ninjutsu|ninja|unblocked attacker", re.IGNORECASE)),
    ("Spell Copy", re.compile(r"copy.*instant|copy.*sorcery|copy.*spell", re.IGNORECASE)),
    ("Toolbox", re.compile(r"search your library|reveal.*put.*hand|tutor", re.IGNORECASE)),
    ("Pillow Fort", re.compile(r"can't attack you|prevent.*damage|propaganda|ghostly prison", re.IGNORECASE)),
    ("Lifedrain", re.compile(r"each opponent loses.*life|drain|gain.*life.*opponent loses", re.IGNORECASE)),
    ("Stompy", re.compile(r"trample|power.*greater|creatures.*get \+\d+/\+\d+", re.IGNORECASE)),
    ("Tempo", re.compile(r"return target.*hand|tap target|counter target|flash", re.IGNORECASE)),
    ("Extra Turns", re.compile(r"take an extra turn|additional turn", re.IGNORECASE)),
    ("Sagas", re.compile(r"saga|lore counter", re.IGNORECASE)),
    ("Clues", re.compile(r"clue|investigate", re.IGNORECASE)),
    ("ETB", re.compile(r"enters the battlefield|enters", re.IGNORECASE)),
    ("Dredge", re.compile(r"dredge|graveyard.*library", re.IGNORECASE)),
    ("Self-Damage", re.compile(r"deals.*damage to you|you lose life|pay.*life", re.IGNORECASE)),
    ("Land Destruction", re.compile(r"destroy target land|destroy all lands|land destruction", re.IGNORECASE)),
    ("Proliferate", re.compile(r"proliferate", re.IGNORECASE)),
    ("Monarch", re.compile(r"monarch", re.IGNORECASE)),
    ("Morph", re.compile(r"morph|manifest|cloak|disguise", re.IGNORECASE)),
    ("Affinity", re.compile(r"affinity|improvise|artifact.*cost.*less", re.IGNORECASE)),
    ("Deathtouch", re.compile(r"deathtouch", re.IGNORECASE)),
    ("Attack Triggers", re.compile(r"whenever.*attacks|attacks.*trigger", re.IGNORECASE)),
    ("Rat Colony", re.compile(r"rat colony|rats you control|rats", re.IGNORECASE)),
    ("Cycling", re.compile(r"cycling", re.IGNORECASE)),
    ("Counterspells", re.compile(r"counter target spell|whenever.*counter", re.IGNORECASE)),
    ("Populate", re.compile(r"populate", re.IGNORECASE)),
    ("Snow", re.compile(r"snow", re.IGNORECASE)),
    ("Defenders", re.compile(r"defender|walls you control", re.IGNORECASE)),
    ("Food", re.compile(r"food", re.IGNORECASE)),
    ("Mutate", re.compile(r"mutate", re.IGNORECASE)),
    ("Prowess", re.compile(r"prowess|noncreature spell", re.IGNORECASE)),
    ("Politics", re.compile(r"vote|council's dilemma|tempting offer|each opponent may", re.IGNORECASE)),
    ("Devotion", re.compile(r"devotion", re.IGNORECASE)),
    ("Pingers", re.compile(r"deals? 1 damage|tap.*damage", re.IGNORECASE)),
    ("Anthems", re.compile(r"creatures you control get|anthem", re.IGNORECASE)),
    ("Fight", re.compile(r"fight|fights", re.IGNORECASE)),
    ("Power", re.compile(r"power|greatest power|power.*or greater", re.IGNORECASE)),
    ("Tap / Untap", re.compile(r"tap target|untap|becomes tapped", re.IGNORECASE)),
    ("Activated Abilities", re.compile(r"activated abilities|activate|activation", re.IGNORECASE)),
    ("Unnatural", re.compile(r"unnatural|odd|weird", re.IGNORECASE)),
    ("Ad Nauseam", re.compile(r"pay.*life|reveal.*mana value|ad nauseam", re.IGNORECASE)),
    ("Dungeon", re.compile(r"dungeon|venture|initiative", re.IGNORECASE)),
    ("Zoo", re.compile(r"creatures you control|beast|cat|dog|ape|kavu", re.IGNORECASE)),
    ("Flash", re.compile(r"flash|as though.*flash", re.IGNORECASE)),
    ("Unblockable", re.compile(r"can't be blocked|unblockable", re.IGNORECASE)),
    ("Sunforger", re.compile(r"instant.*mana value.*4|equipment", re.IGNORECASE)),
    ("Sea Creatures", re.compile(r"kraken|leviathan|octopus|serpent|fish", re.IGNORECASE)),
    ("Foretell", re.compile(r"foretell", re.IGNORECASE)),
    ("Cheerios", re.compile(r"mana value 0|costs? \{0\}|equipment.*cost.*0", re.IGNORECASE)),
    ("Discover", re.compile(r"discover", re.IGNORECASE)),
    ("Triggered Abilities", re.compile(r"whenever|at the beginning|triggered ability", re.IGNORECASE)),
    ("Dragon's Approach", re.compile(r"dragon's approach|dragon.*approach", re.IGNORECASE)),
    ("Party", re.compile(r"party|cleric|rogue|warrior|wizard", re.IGNORECASE)),
    ("Curses", re.compile(r"curse|enchanted player", re.IGNORECASE)),
    ("Bounce", re.compile(r"return target.*hand|return.*to.*owner's hand", re.IGNORECASE)),
    ("Donate", re.compile(r"target opponent gains control|exchange control", re.IGNORECASE)),
    ("Eggs", re.compile(r"sacrifice.*draw a card|when.*put into.*graveyard.*draw", re.IGNORECASE)),
    ("Shadowborn Apostles", re.compile(r"shadowborn apostle|apostle", re.IGNORECASE)),
    ("Keywords", re.compile(r"flying|first strike|double strike|deathtouch|haste|hexproof|indestructible|lifelink|trample|vigilance", re.IGNORECASE)),
    ("Modified Creatures", re.compile(r"modified|equipped|enchanted|counter.*on it", re.IGNORECASE)),
    ("Persistent Petitioners", re.compile(r"persistent petitioners|advisor", re.IGNORECASE)),
    ("Aikido", re.compile(r"prevent.*damage|redirect|deals that much damage", re.IGNORECASE)),
    ("Self-Discard", re.compile(r"discard.*card|madness", re.IGNORECASE)),
    ("Haste", re.compile(r"haste", re.IGNORECASE)),
    ("Prison", re.compile(r"can't attack|can't cast|can't untap|skip.*step", re.IGNORECASE)),
    ("Flashback", re.compile(r"flashback|cast.*from.*graveyard", re.IGNORECASE)),
    ("Madness", re.compile(r"madness", re.IGNORECASE)),
    ("Counters Matter", re.compile(r"counter.*on|remove.*counter|put.*counter", re.IGNORECASE)),
    ("Multicolor Matters", re.compile(r"colors among|multicolored|for each color", re.IGNORECASE)),
    ("Primal Surge", re.compile(r"permanent cards|nonpermanent|primal surge", re.IGNORECASE)),
    ("Kaheera Companion", re.compile(r"cat|elemental|nightmare|dinosaur|beast", re.IGNORECASE)),
    ("Impulse Draw", re.compile(r"exile.*top.*you may play|until end of turn.*play", re.IGNORECASE)),
    ("Convoke", re.compile(r"convoke|tap.*creatures.*pay", re.IGNORECASE)),
    ("Modular", re.compile(r"modular", re.IGNORECASE)),
    ("Rock", re.compile(r"destroy target|draw.*card|creature.*dies|grindy", re.IGNORECASE)),
    ("Polymorph", re.compile(r"reveal.*creature.*library|polymorph|transform.*creature", re.IGNORECASE)),
    ("Scry", re.compile(r"scry", re.IGNORECASE)),
    ("Guildgates", re.compile(r"gate|guildgate", re.IGNORECASE)),
    ("Coin Flip", re.compile(r"coin flip|flip.*coin", re.IGNORECASE)),
    ("Earthbending", re.compile(r"earthbend|earthbending|land.*creature", re.IGNORECASE)),
    ("Tron", re.compile(r"urza's|power-plant|mine|tower", re.IGNORECASE)),
    ("Die Roll", re.compile(r"roll.*d\d+|roll.*die", re.IGNORECASE)),
    ("Weenies", re.compile(r"creatures.*mana value 1|small creatures|tokens", re.IGNORECASE)),
    ("Amass", re.compile(r"amass|army", re.IGNORECASE)),
    ("Land Animation", re.compile(r"land.*becomes.*creature|animate.*land", re.IGNORECASE)),
    ("Relentless Rats", re.compile(r"relentless rats|rats", re.IGNORECASE)),
    ("The Ring", re.compile(r"the ring tempts you|ring-bearer", re.IGNORECASE)),
    ("Attractions", re.compile(r"attraction|visit", re.IGNORECASE)),
    ("Fling", re.compile(r"sacrifice.*creature.*damage|fling", re.IGNORECASE)),
    ("Experience Counters", re.compile(r"experience counter", re.IGNORECASE)),
    ("Shrines", re.compile(r"shrine", re.IGNORECASE)),
    ("Utility / Value", re.compile(r"draw.*card|create.*token|destroy target|exile target|search your library", re.IGNORECASE)),
]

BROAD_COMMANDER_ROLES = {
    "Aggro", "Midrange", "Good Stuff", "Utility / Value", "Triggered Abilities",
    "Keywords", "Power", "Rock", "Unnatural",
}

ROLE_SPECIFICITY_BOOST = {
    "Equipment": 12,
    "Auras": 12,
    "Enchantress": 10,
    "Artifacts": 8,
    "Spellslinger": 8,
    "Aristocrats": 8,
    "Reanimator": 8,
    "Lands Matter": 8,
    "Landfall": 8,
    "Treasure": 8,
    "Voltron": 8,
    "Blink": 8,
    "Mill": 8,
    "Stax": 8,
    "Storm": 8,
    "Combo": 8,
}

COMMANDER_ROLE_PATTERNS = {name: pattern for name, pattern in COMMANDER_ROLES}


# ─── Role-specific card suggestions (name + required color identity) ──────────
# ci: [] means colorless — fits ANY commander's color identity.
# ci: ["G"] means the card requires Green; filtered out if commander isn't Green.

ROLE_SUGGESTIONS: dict[str, list[dict]] = {
    "Token Engine": [
        {"name": "Anointed Procession",  "ci": ["W"]},
        {"name": "Parallel Lives",       "ci": ["G"]},
        {"name": "Doubling Season",      "ci": ["G"]},
        {"name": "Ashnod's Altar",       "ci": []},
        {"name": "Skullclamp",           "ci": []},
        {"name": "Viscera Seer",         "ci": ["B"]},
        {"name": "Intangible Virtue",    "ci": ["W"]},
        {"name": "Cathars' Crusade",     "ci": ["W"]},
        {"name": "Teysa Karlov",         "ci": ["W", "B"]},
        {"name": "Blade of Shared Souls", "ci": []},
    ],
    "Card Draw Engine": [
        {"name": "Rhystic Study",        "ci": ["U"]},
        {"name": "Mystic Remora",        "ci": ["U"]},
        {"name": "Phyrexian Arena",      "ci": ["B"]},
        {"name": "Sylvan Library",       "ci": ["G"]},
        {"name": "Necropotence",         "ci": ["B"]},
        {"name": "Smothering Tithe",     "ci": ["W"]},
        {"name": "Skullclamp",           "ci": []},
        {"name": "Harmonize",            "ci": ["G"]},
    ],
    "Ramp Engine": [
        {"name": "Selvala, Heart of the Wilds", "ci": ["G"]},
        {"name": "Gilded Lotus",         "ci": []},
        {"name": "Smothering Tithe",     "ci": ["W"]},
        {"name": "Urborg, Tomb of Yawgmoth", "ci": ["B"]},
        {"name": "Springbloom Druid",    "ci": ["G"]},
        {"name": "Vorinclex, Voice of Hunger", "ci": ["G"]},
        {"name": "Sol Ring",             "ci": []},
    ],
    "Aristocrats": [
        {"name": "Skullclamp",           "ci": []},
        {"name": "Ashnod's Altar",       "ci": []},
        {"name": "Viscera Seer",         "ci": ["B"]},
        {"name": "Blood Artist",         "ci": ["B"]},
        {"name": "Zulaport Cutthroat",   "ci": ["B"]},
        {"name": "Dictate of Erebos",    "ci": ["B"]},
        {"name": "Grave Pact",           "ci": ["B"]},
        {"name": "Sifter of Skulls",     "ci": []},
    ],
    "Spellslinger": [
        {"name": "Young Pyromancer",     "ci": ["R"]},
        {"name": "Monastery Mentor",     "ci": ["W"]},
        {"name": "Murmuring Mystic",     "ci": ["U"]},
        {"name": "Thousand-Year Storm",  "ci": ["U", "R"]},
        {"name": "Guttersnipe",          "ci": ["R"]},
        {"name": "Niv-Mizzet, Parun",   "ci": ["U", "R"]},
        {"name": "Sentinel Tower",       "ci": []},
        {"name": "Aria of Flame",        "ci": ["R"]},
    ],
    "Enchantress": [
        {"name": "Enchantress's Presence", "ci": ["G"]},
        {"name": "Argothian Enchantress",  "ci": ["G"]},
        {"name": "Setessan Champion",    "ci": ["G"]},
        {"name": "Sythis, Harvest's Hand", "ci": ["G", "W"]},
        {"name": "Mesa Enchantress",     "ci": ["W"]},
        {"name": "Eidolon of Blossoms",  "ci": ["G"]},
        {"name": "Sanctum Weaver",       "ci": ["G"]},
    ],
    "Artifact Matters": [
        {"name": "Sai, Master Thopterist", "ci": ["U"]},
        {"name": "Vedalken Archmage",    "ci": ["U"]},
        {"name": "Whir of Invention",    "ci": ["U"]},
        {"name": "Mirrodin Besieged",    "ci": ["U"]},
        {"name": "Urza, Lord High Artificer", "ci": ["U"]},
        {"name": "Goblin Welder",        "ci": ["R"]},
        {"name": "Shimmer Myr",          "ci": []},
    ],
    "Proliferate Engine": [
        {"name": "Contagion Engine",     "ci": []},
        {"name": "Inexorable Tide",      "ci": ["U"]},
        {"name": "Evolution Sage",       "ci": ["G"]},
        {"name": "Tekuthal, Inquiry Dominus", "ci": ["U"]},
        {"name": "Sword of Truth and Justice", "ci": []},
        {"name": "Fuel for the Cause",   "ci": ["U"]},
        {"name": "Throne of Geth",       "ci": []},
    ],
    "Counters Engine": [
        {"name": "Hardened Scales",      "ci": ["G"]},
        {"name": "Vorinclex, Monstrous Raider", "ci": ["G"]},
        {"name": "Ozolith, the Shattered Spire", "ci": ["G"]},
        {"name": "Beastmaster Ascension", "ci": ["G"]},
        {"name": "Overwhelming Stampede", "ci": ["G"]},
        {"name": "Branching Evolution",  "ci": ["G"]},
        {"name": "Conclave Mentor",      "ci": ["G", "W"]},
    ],
    "Landfall": [
        {"name": "Avenger of Zendikar",  "ci": ["G"]},
        {"name": "Scute Swarm",          "ci": ["G"]},
        {"name": "Omnath, Locus of Rage", "ci": ["R", "G"]},
        {"name": "Field of the Dead",    "ci": []},
        {"name": "Moraug, Fury of Akoum", "ci": ["R"]},
        {"name": "Aesi, Tyrant of Gyre Strait", "ci": ["U", "G"]},
        {"name": "Lotus Cobra",          "ci": ["G"]},
    ],
    "Combat Damage": [
        {"name": "Lightning Greaves",    "ci": []},
        {"name": "Swiftfoot Boots",      "ci": []},
        {"name": "Bident of Thassa",     "ci": ["U"]},
        {"name": "Coastal Piracy",       "ci": ["U"]},
        {"name": "Aggravated Assault",   "ci": ["R"]},
        {"name": "Reconnaissance",       "ci": ["W"]},
        {"name": "Fireshrieker",         "ci": []},
        {"name": "Sword of Feast and Famine", "ci": []},
    ],
    "Graveyard Engine": [
        {"name": "Reanimate",            "ci": ["B"]},
        {"name": "Animate Dead",         "ci": ["B"]},
        {"name": "Entomb",               "ci": ["B"]},
        {"name": "Buried Alive",         "ci": ["B"]},
        {"name": "Skullclamp",           "ci": []},
        {"name": "Victimize",            "ci": ["B"]},
        {"name": "Necromancy",           "ci": ["B"]},
        {"name": "Phyrexian Reclamation", "ci": ["B"]},
    ],
    "Storm / Combo": [
        {"name": "Dramatic Reversal",    "ci": ["U"]},
        {"name": "Isochron Scepter",     "ci": []},
        {"name": "Demonic Tutor",        "ci": ["B"]},
        {"name": "Mystical Tutor",       "ci": ["U"]},
        {"name": "Underworld Breach",    "ci": ["R"]},
        {"name": "Brain Freeze",         "ci": ["U"]},
        {"name": "Thassa's Oracle",      "ci": ["U"]},
        {"name": "Sensei's Divining Top", "ci": []},
    ],
    "Beatdown": [
        {"name": "Lightning Greaves",    "ci": []},
        {"name": "Swiftfoot Boots",      "ci": []},
        {"name": "Fireshrieker",         "ci": []},
        {"name": "Sword of Feast and Famine", "ci": []},
        {"name": "Embercleave",          "ci": ["R"]},
        {"name": "Hatred",               "ci": ["B"]},
        {"name": "Temur Battle Rage",    "ci": ["R"]},
    ],
    "Utility / Value": [
        {"name": "Sol Ring",             "ci": []},
        {"name": "Arcane Signet",        "ci": []},
        {"name": "Rhystic Study",        "ci": ["U"]},
        {"name": "Swords to Plowshares", "ci": ["W"]},
        {"name": "Path to Exile",        "ci": ["W"]},
        {"name": "Counterspell",         "ci": ["U"]},
        {"name": "Cyclonic Rift",        "ci": ["U"]},
        {"name": "Demonic Tutor",        "ci": ["B"]},
    ],
}

ROLE_SUGGESTION_ALIASES = {
    "Tokens": "Token Engine",
    "+1/+1 Counters": "Counters Engine",
    "-1/-1 Counters": "Counters Engine",
    "Counters Matter": "Counters Engine",
    "Artifacts": "Artifact Matters",
    "Treasure": "Artifact Matters",
    "Affinity": "Artifact Matters",
    "Historic": "Artifact Matters",
    "Card Draw": "Card Draw Engine",
    "Impulse Draw": "Card Draw Engine",
    "Ramp": "Ramp Engine",
    "Big Mana": "Ramp Engine",
    "Lands Matter": "Landfall",
    "Landfall": "Landfall",
    "Land Animation": "Landfall",
    "Spellslinger": "Spellslinger",
    "Cantrips": "Spellslinger",
    "Spell Copy": "Spellslinger",
    "Storm": "Storm / Combo",
    "Combo": "Storm / Combo",
    "cEDH": "Storm / Combo",
    "Ad Nauseam": "Storm / Combo",
    "Graveyard": "Graveyard Engine",
    "Reanimator": "Graveyard Engine",
    "Self-Mill": "Graveyard Engine",
    "Dredge": "Graveyard Engine",
    "Aristocrats": "Aristocrats",
    "Sacrifice": "Aristocrats",
    "Lifedrain": "Aristocrats",
    "Enchantress": "Enchantress",
    "Auras": "Enchantress",
    "Sagas": "Enchantress",
    "Voltron": "Combat Damage",
    "Equipment": "Combat Damage",
    "Attack Triggers": "Combat Damage",
    "Flying": "Combat Damage",
    "Unblockable": "Combat Damage",
    "Aggro": "Beatdown",
    "Stompy": "Beatdown",
    "Infect": "Beatdown",
}


def _scryfall_url(name: str) -> str:
    return "https://scryfall.com/search?q=!" + urllib.parse.quote(f'"{name}"')


def _role_description(role: str) -> str:
    meta = get_role_metadata(role)
    if meta:
        return meta["description"]
    return f"Builds around {role} synergies as the deck's main plan."


def _confidence(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 38:
        return "medium"
    return "low"


def _safe_power(entry: CardEntry) -> int:
    try:
        return int(entry.power or 0)
    except ValueError:
        return 0


def _theme_text(entry: CardEntry) -> str:
    return " ".join(
        part for part in [
            entry.name or "",
            entry.type_line or "",
            entry.oracle_text or "",
            " ".join(entry.keywords or []),
        ]
        if part
    )


def _oracle_text(entry: CardEntry | None) -> str:
    if not entry:
        return ""
    return " ".join(part for part in [entry.oracle_text or "", " ".join(entry.keywords or [])] if part)


def _creature_subtypes(entry: CardEntry) -> list[str]:
    if not entry.is_creature or not entry.type_line:
        return []
    if "—" not in entry.type_line:
        return []
    subtype_text = entry.type_line.split("—", 1)[1]
    return [part.strip() for part in subtype_text.split() if part.strip()]


def _singularize_type(name: str) -> str:
    clean = name.strip()
    lowered = clean.lower()
    irregular = {
        "elves": "elf",
        "phyrexians": "phyrexian",
        "time lords": "time lord",
    }
    if lowered in irregular:
        return irregular[lowered]
    if lowered.endswith("ies"):
        return lowered[:-3] + "y"
    if lowered.endswith("ses") or lowered.endswith("xes") or lowered.endswith("ches") or lowered.endswith("shes"):
        return lowered[:-2]
    if lowered.endswith("s"):
        return lowered[:-1]
    return lowered


def _theme_deck_evidence(role: str, entries: list[CardEntry], pattern: re.Pattern | None) -> tuple[float, list[str]]:
    non_commanders = [e for e in entries if e.found and not e.is_commander]
    evidence: list[str] = []
    score = 0.0
    if not non_commanders:
        return score, evidence

    if pattern:
        matches = [
            e for e in non_commanders
            if pattern.search(_theme_text(e))
        ]
        match_qty = sum(e.quantity for e in matches)
        if match_qty:
            score += min(32, match_qty * 2.4)
            evidence.append(f"{match_qty} deck card(s) match {role} text")

    if role in {"Artifacts", "Affinity"}:
        count = sum(e.quantity for e in non_commanders if e.is_artifact)
        if count >= 8:
            score += min(28, count * 1.8)
            evidence.append(f"{count} artifact card(s)")
    elif role in {"Enchantress", "Auras", "Sagas"}:
        count = sum(e.quantity for e in non_commanders if e.is_enchantment)
        if count >= 8:
            score += min(28, count * 1.8)
            evidence.append(f"{count} enchantment card(s)")
    elif role in {"Spellslinger", "Cantrips", "Storm", "Spell Copy"}:
        count = sum(e.quantity for e in non_commanders if e.is_instant or e.is_sorcery)
        if count >= 16:
            score += min(28, count * 1.2)
            evidence.append(f"{count} instant/sorcery card(s)")
    elif role in {"Lands Matter", "Landfall", "Land Animation"}:
        count = sum(e.quantity for e in non_commanders if e.is_land)
        land_text = sum(
            e.quantity for e in non_commanders
            if re.search(r"landfall|land.*enters|play.*additional land|return.*land", _theme_text(e), re.IGNORECASE)
        )
        if count >= 38 or land_text >= 4:
            score += min(28, max(0, count - 34) * 2 + land_text * 4)
            evidence.append(f"{count} lands and {land_text} land-synergy card(s)")
    elif role in {"Voltron", "Equipment"}:
        equipment = sum(e.quantity for e in non_commanders if "Equipment" in (e.type_line or ""))
        aura = sum(e.quantity for e in non_commanders if "Aura" in (e.type_line or ""))
        if equipment + aura >= 6:
            score += min(28, (equipment + aura) * 3)
            evidence.append(f"{equipment} Equipment and {aura} Aura card(s)")

    return score, evidence[:2]


def _score_theme_roles(commander: CardEntry | None, entries: list[CardEntry]) -> list[dict]:
    matches: list[dict] = []
    commander_text = _oracle_text(commander) if commander and commander.found else ""
    for catalog_entry in get_role_catalog_entries():
        if catalog_entry.kind != "theme":
            continue
        pattern = COMMANDER_ROLE_PATTERNS.get(catalog_entry.name)
        score = 0.0
        evidence: list[str] = []
        if pattern and commander_text and pattern.search(commander_text):
            score += 55
            evidence.append("commander text matches")
        deck_score, deck_evidence = _theme_deck_evidence(catalog_entry.name, entries, pattern)
        score += deck_score
        evidence.extend(deck_evidence)
        if catalog_entry.name in ROLE_SPECIFICITY_BOOST:
            score += ROLE_SPECIFICITY_BOOST[catalog_entry.name]
        if catalog_entry.name in BROAD_COMMANDER_ROLES:
            score -= 18
        if catalog_entry.deck_count:
            score += min(6, catalog_entry.deck_count / 35000)
        if score >= 18:
            matches.append({
                "name": catalog_entry.name,
                "kind": catalog_entry.kind,
                "score": round(score, 1),
                "confidence": _confidence(score),
                "description": catalog_entry.description,
                "evidence": evidence[:3] or ["matched deck pattern"],
                "deck_count": catalog_entry.deck_count,
            })

    if commander and commander.found and not matches and commander.is_creature and _safe_power(commander) >= _HIGH_POWER_THRESH:
        meta = get_role_metadata("Aggro") or {}
        matches.append({
            "name": "Aggro",
            "kind": "theme",
            "score": 30,
            "confidence": "low",
            "description": meta.get("description", _role_description("Aggro")),
            "evidence": [f"{commander.name} is a high-power creature"],
            "deck_count": meta.get("deck_count", 0),
        })
    return matches


def _score_typal_roles(commander: CardEntry | None, entries: list[CardEntry]) -> list[dict]:
    found = [e for e in entries if e.found]
    non_commander_creatures = [e for e in found if e.is_creature and not e.is_commander]
    creature_total = sum(e.quantity for e in non_commander_creatures)
    subtype_counts: Counter = Counter()
    for entry in non_commander_creatures:
        for subtype in _creature_subtypes(entry):
            subtype_counts[_singularize_type(subtype)] += entry.quantity

    commander_text = _oracle_text(commander) if commander and commander.found else ""
    commander_subtypes = {
        _singularize_type(subtype)
        for subtype in _creature_subtypes(commander)
    } if commander else set()

    matches: list[dict] = []
    for catalog_entry in get_role_catalog_entries():
        if catalog_entry.kind != "typal":
            continue
        singular = _singularize_type(catalog_entry.name)
        count = subtype_counts.get(singular, 0)
        density = (count / creature_total) if creature_total else 0
        score = 0.0
        evidence: list[str] = []
        if commander_text and re.search(rf"\b{re.escape(catalog_entry.name)}\b|\b{re.escape(singular)}\b", commander_text, re.IGNORECASE):
            score += 55
            evidence.append("commander text mentions the creature type")
        if singular in commander_subtypes:
            score += 8
            evidence.append("commander has the creature type")
        if count >= 8 and density >= 0.28:
            score += min(48, count * 2.4 + density * 25)
            evidence.append(f"{count} {catalog_entry.name} in the deck")
        elif count >= 12:
            score += min(34, count * 1.8)
            evidence.append(f"{count} {catalog_entry.name} in the deck")
        if catalog_entry.deck_count:
            score += min(5, catalog_entry.deck_count / 7000)
        if score >= 28:
            matches.append({
                "name": catalog_entry.name,
                "kind": catalog_entry.kind,
                "score": round(score, 1),
                "confidence": _confidence(score),
                "description": catalog_entry.description,
                "evidence": evidence[:3],
                "deck_count": catalog_entry.deck_count,
            })
    return matches


def detect_commander_role_matches(
    commander: CardEntry | None,
    entries: list[CardEntry] | None = None,
    limit: int = 5,
) -> list[dict]:
    """Return ranked commander/deck theme matches with evidence."""
    if commander and not commander.found:
        return [{
            "name": "Unknown",
            "kind": "theme",
            "score": 0,
            "confidence": "low",
            "description": "Commander was not found in the local card index.",
            "evidence": ["commander lookup failed"],
            "deck_count": 0,
        }]

    pool = list(entries or ([commander] if commander else []))
    matches = _score_theme_roles(commander, pool) + _score_typal_roles(commander, pool)
    specific_matches = [match for match in matches if match["name"] not in BROAD_COMMANDER_ROLES]
    if len(specific_matches) >= 3:
        matches = specific_matches
    matches.sort(key=lambda item: (item["score"], item.get("deck_count", 0)), reverse=True)

    filtered: list[dict] = []
    seen: set[str] = set()
    for match in matches:
        key = match["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        filtered.append(match)
        if len(filtered) >= limit:
            break

    if filtered:
        return filtered

    meta = get_role_metadata("Utility / Value") or {}
    return [{
        "name": "Utility / Value",
        "kind": "theme",
        "score": 0,
        "confidence": "low",
        "description": meta.get("description", "Provides general value without a strongly detected theme."),
        "evidence": ["no stronger EDHREC theme detected"],
        "deck_count": meta.get("deck_count", 0),
    }]


def detect_commander_role(commander: CardEntry, entries: list[CardEntry] | None = None) -> list[str]:
    """Return the most relevant commander/deck role names."""
    return [match["name"] for match in detect_commander_role_matches(commander, entries)]


def commander_focus_advice(roles: list[str], color_identity: list[str] | None = None) -> dict:
    """
    Return advice and color-filtered card suggestions for the commander's role.
    Returns {"text": str, "suggested_cards": [{"name": str, "url": str}]}.
    """
    advice_map = {
        "Tokens":            "Your commander points toward tokens — prioritize token doublers, sacrifice outlets, and anthem effects as Plan enhancers.",
        "+1/+1 Counters":    "Your commander builds +1/+1 counters — focus Plan cards on counter multipliers, evasion, and ways to turn large boards into lethal pressure.",
        "Artifacts":         "Your commander rewards artifacts — cheap rocks and utility artifacts can serve as Ramp, Plan enablers, and sometimes Card Advantage at once.",
        "Combo":             "Your commander suggests a combo plan — keep the combo package compact, add protection, and make sure tutors or draw effects find the pieces reliably.",
        "Lifegain":          "Your commander rewards life gain — balance repeatable lifegain enablers with payoffs that convert life into cards, damage, or board presence.",
        "Aggro":             "Your commander wants pressure — prioritize efficient threats, haste or evasion, and interaction that keeps blockers out of the way.",
        "Reanimator":        "Your commander supports reanimation — use self-mill and discard as enablers, then add high-impact creatures worth returning to the battlefield.",
        "Lands Matter":      "Your commander cares about lands — prioritize extra land drops, fetch effects, and payoffs that reward lands entering the battlefield.",
        "Treasure":          "Your commander makes or rewards Treasures — treat Treasures as both ramp and artifact-plan enablers, then add payoffs that convert them into cards or damage.",
        "Equipment":         "Your commander cares about Equipment — prioritize cheap equips, protection, and combat-damage payoffs that keep the commander relevant.",
        "Control":           "Your commander supports control — make sure card advantage and flexible interaction are high enough to survive until your finishers matter.",
        "Burn":              "Your commander points toward burn — prioritize repeatable damage engines and ways to multiply noncombat damage.",
        "Mill":              "Your commander supports mill — add repeatable mill engines, graveyard hate awareness, and a clear way to finish before opponents benefit from stocked graveyards.",
        "Voltron":           "Your commander is a Voltron threat — prioritize protection, evasion, and cheap power boosts that keep commander damage online.",
        "Sacrifice":         "Your commander rewards sacrifice — add disposable bodies, free sacrifice outlets, and death-trigger payoffs.",
        "Wheels":            "Your commander rewards wheels — prioritize draw-punish payoffs, mana generation, and graveyard plans that benefit from discarded hands.",
        "Blink":             "Your commander supports blink — prioritize creatures with strong enter-the-battlefield effects and instant-speed blink protection.",
        "Discard":           "Your commander rewards discard — balance hand disruption with payoffs that turn discarded cards into damage, tokens, or reanimation value.",
        "Clones":            "Your commander rewards copies — prioritize high-impact targets and clone effects that scale with your best permanent on board.",
        "Flying":            "Your commander points toward flying — prioritize evasive threats, aerial anthems, and card draw tied to combat damage.",
        "Infect":            "Your commander enables poison pressure — prioritize protection, proliferation, and ways to force damage through blockers.",
        "Big Mana":          "Your commander supports big mana — keep ramp dense, then spend it on cards that immediately stabilize or threaten a win.",
        "Stax":              "Your commander supports stax — pair disruptive permanents with asymmetrical effects so your deck can operate while opponents are slowed.",
        "Group Slug":        "Your commander pressures the whole table — add repeatable damage and lifegain or prevention tools so you can survive your own clock.",
        "Storm":             "Your commander rewards storm lines — prioritize cheap spells, rituals or cost reducers, and clear payoff cards.",
        "Planeswalkers":     "Your commander supports planeswalkers — prioritize protection, proliferate, and board control that lets loyalty abilities compound.",
        "Extra Combats":     "Your commander rewards combat loops — add haste, vigilance or untap effects, and payoffs that make each combat step matter.",
        "Graveyard":         "Your commander leverages the graveyard — self-mill counts as Card Advantage. Enablers and payoffs should dominate your Plan slots.",
        "Token Engine":       "Your commander generates tokens — prioritize token doublers and sacrifice outlets or anthem effects as Plan enhancers.",
        "Card Draw Engine":   "Your commander draws cards — support it with cheap spells and protection. Focus Plan cards on payoffs that reward having many cards.",
        "Ramp Engine":        "Your commander ramps — lean into high-CMC payoffs (7+ slot). Make sure non-land cards provide meaningful late-game value.",
        "Aristocrats":        "Your commander rewards sacrifice — build around cheap token generators (enablers) and death-triggers (payoffs). Skullclamp doubles as Card Advantage.",
        "Spellslinger":       "Your commander rewards casting spells — prioritize instants/sorceries as plan pieces. Cheap cantrips count as both Card Advantage and enablers.",
        "Enchantress":        "Your commander cares about enchantments — lean into enchantress draw effects and auras. Many enchantments double as removal or ramp, covering multiple categories.",
        "Artifact Matters":   "Your commander rewards artifacts — cheap mana rocks serve double duty as Ramp AND Plan enablers, compressing your required card slots.",
        "Proliferate Engine": "Your commander proliferates — prioritize planeswalkers and +1/+1 counter payoffs. Ramp rocks like Astral Cornucopia grow with proliferate.",
        "Counters Engine":    "Your commander builds counters — focus Plan cards on payoffs that reward large creatures and trample through.",
        "Landfall":           "Your commander triggers on lands — prioritize fetch lands and ramp spells that put lands directly into play. Extra land drops are both Ramp AND Plan enablers.",
        "Combat Damage":      "Your commander triggers on combat damage — prioritize evasion, protection, and haste. Voltron equipment compresses Removal and Plan into one category.",
        "Graveyard Engine":   "Your commander leverages the graveyard — self-mill counts as Card Advantage. Enablers (sac outlets) and payoffs (reanimation) should dominate your Plan slots.",
        "Storm / Combo":      "Your commander combos — prioritize fast mana and tutors. Your Plan Cards should have a clear 2-3 card combo package as the primary win condition.",
        "Beatdown":           "Your commander is a threat — protect it and give it evasion. Focus Plan cards on enabling commander damage wins.",
        "Utility / Value":    "Your commander provides general value — balance all six categories evenly. Look for cards that cover 2+ categories to maximize slot efficiency.",
    }

    role = roles[0] if roles else "Utility / Value"
    advice_role = next((r for r in roles if r in advice_map), None)
    if advice_role:
        text = advice_map[advice_role]
    else:
        text = (
            f"Your commander points toward a {role} plan — keep the core theme dense, "
            "then prioritize cards that also cover ramp, card advantage, or interaction."
        )

    # Filter suggestions by the commander's color identity
    ci_set = set(color_identity) if color_identity else set("WUBRG")
    suggestion_role = ROLE_SUGGESTION_ALIASES.get(role, role)
    raw = ROLE_SUGGESTIONS.get(suggestion_role, ROLE_SUGGESTIONS["Utility / Value"])

    def _fits(card: dict) -> bool:
        if not card["ci"]:
            return True  # colorless — always legal
        return all(c in ci_set for c in card["ci"])

    suggested_cards = [
        {"name": c["name"], "url": _scryfall_url(c["name"])}
        for c in raw if _fits(c)
    ][:6]

    return {"text": text, "suggested_cards": suggested_cards}


# ─── Multi-role tagging ───────────────────────────────────────────────────────

def _should_add_plan_cards(entry: CardEntry, current_roles: list[str]) -> bool:
    """Whether a card with otag-assigned roles should also receive Plan Cards."""
    if "Plan Cards" in current_roles:
        return False
    txt = entry.oracle_text or ""
    if _PLAN_ENABLER.search(txt) or _PLAN_PAYOFF.search(txt):
        return True
    if entry.is_creature and not current_roles:
        return True
    if entry.is_creature and entry.power and entry.power.isdigit() and int(entry.power) >= _HIGH_POWER_THRESH:
        return True
    if entry.is_planeswalker:
        return True
    if entry.is_enchantment and "Removal" not in current_roles:
        return True
    return False


def assign_roles(entry: CardEntry) -> list[str]:
    """
    Assign one or more framework categories to a card.
    A card CAN fill multiple roles — that's the overlap that lets you hit 100 cards.
    Uses otag index as primary source; falls back to regex if the card isn't indexed.
    """
    roles = []
    txt = entry.oracle_text or ""
    tl = entry.type_line or ""

    if entry.is_land:
        roles.append("Lands")
        return roles  # lands don't double as anything else for our purposes

    # Primary: otag lookup (getattr guards against SimpleNamespace proxies for EDHREC cards)
    otags = lookup_otags(getattr(entry, "name", "") or "")
    if otags:
        for tag in otags:
            for cat in _OTAG_CATEGORY_MAP.get(tag, []):
                if cat not in roles:
                    roles.append(cat)
        if _should_add_plan_cards(entry, roles):
            roles.append("Plan Cards")
        if not roles:
            roles.append("Plan Cards")
        return roles

    # Fallback: regex-based classification for cards not in the otag index
    if _BOARDWIPE.search(txt):
        roles.append("Mass Disruption")
    elif _MASS_DISRUPTION_NONWIPE.search(txt) and not entry.is_creature:
        roles.append("Mass Disruption")

    if _REMOVAL.search(txt):
        roles.append("Removal")

    if _CARD_ADVANTAGE.search(txt):
        roles.append("Card Advantage")

    # Ramp: pattern match OR cheap mana dork creature
    is_mana_creature = (
        entry.is_creature
        and (entry.cmc or 0) <= 2
        and _RAMP.search(txt)
    )
    if _RAMP.search(txt) or is_mana_creature:
        roles.append("Ramp")

    # Plan Cards: anything that isn't purely utility fits here
    # Avoid double-counting purely removal/ramp spells as plan cards unless they also synergize
    is_plan = False
    if _PLAN_ENABLER.search(txt) or _PLAN_PAYOFF.search(txt):
        is_plan = True
    if entry.is_creature and not roles:
        is_plan = True  # most creatures are plan pieces
    if entry.is_creature and entry.power and entry.power.isdigit() and int(entry.power) >= _HIGH_POWER_THRESH:
        is_plan = True
    if entry.is_planeswalker:
        is_plan = True
    if entry.is_enchantment and "Removal" not in roles:
        is_plan = True

    if is_plan:
        roles.append("Plan Cards")

    # Anything still uncategorized: call it a plan card
    if not roles:
        roles.append("Plan Cards")

    return roles


def subcategorize_plan_card(entry: CardEntry, commander_roles: list[str]) -> str:
    """
    Classify a Plan Card as Enabler, Payoff, or Enhancer.
    Enabler  — sets up the strategy (needs other cards to work)
    Payoff   — rewards the strategy happening (win conditions, big value)
    Enhancer — multiplies the plan (doublers, anthems, cost reducers)
    """
    txt = entry.oracle_text or ""

    # Enhancers — doublers and multipliers
    if re.search(r"double|twice as many|multiplied|cost.*less|reduced|whenever.*each", txt, re.IGNORECASE):
        return "Enhancer"

    # Payoffs — clear reward/win condition language
    if re.search(
        r"you win|loses.*life|deal.*damage.*each|opponents.*lose|"
        r"draw.*equal.*number|create.*for each|gain.*for each",
        txt, re.IGNORECASE
    ):
        return "Payoff"

    # High-power finishers
    if entry.is_creature and entry.power and entry.power.isdigit() and int(entry.power) >= 6:
        return "Payoff"

    # Planeswalkers with ultimate abilities are usually payoffs
    if entry.is_planeswalker:
        return "Payoff"

    # Default: Enabler
    return "Enabler"


# ─── CMC curve evaluation ─────────────────────────────────────────────────────

def evaluate_curve(entries: list[CardEntry]) -> dict:
    """Compare actual CMC distribution (non-land) to the ideal target curve."""
    non_land = [e for e in entries if e.found and not e.is_land and not e.is_commander]
    actual: Counter = Counter()
    for e in non_land:
        cmc = int(e.cmc) if e.cmc is not None else 0
        bucket = min(cmc, 7)
        actual[bucket] += e.quantity

    comparison = {}
    notes = []
    for cmc, target in IDEAL_CURVE.items():
        act = actual.get(cmc, 0)
        label = f"{cmc}+" if cmc == 7 else str(cmc)
        diff = act - target
        comparison[label] = {"actual": act, "target": target, "diff": diff}

    # Sticky points: CMC buckets where actual is materially below target
    for cmc, target in IDEAL_CURVE.items():
        act = actual.get(cmc, 0)
        label = f"{cmc}+" if cmc == 7 else str(cmc)
        if target > 0 and act < target * 0.6:
            notes.append(
                f"CMC {label} is light ({act} actual vs {target} target) — "
                f"consider adding {target - act} more card(s) at this cost."
            )
        elif act > target * 1.5 and target > 0:
            notes.append(
                f"CMC {label} is heavy ({act} actual vs {target} target) — "
                f"you may struggle in the early game or find dead turns."
            )

    # Total non-land count
    total_nonland = sum(actual.values())
    if total_nonland < 58:
        notes.append(
            f"Only {total_nonland} non-land cards (lands + non-lands should total 100). "
            "Check your land count."
        )

    return {"comparison": comparison, "notes": notes, "total_nonland": total_nonland}


# ─── Path to Victory ──────────────────────────────────────────────────────────

def path_to_victory(entries: list[CardEntry], multi_roles: dict[str, list[str]]) -> dict:
    """
    Estimate whether the deck has a clear path to a win condition by turn 5.
    Factors: payoff density, curve, ramp count, commander CMC.
    """
    found = [e for e in entries if e.found]

    # Get commander CMC
    commanders = [e for e in found if e.is_commander]
    cmd_cmc = commanders[0].cmc if commanders else 4
    cmd_name = commanders[0].name if commanders else "your commander"

    ramp_count = sum(1 for e in found if "Ramp" in multi_roles.get(e.name or "", []))
    payoff_cards = [
        e for e in found
        if "Plan Cards" in multi_roles.get(e.name or "", [])
        and subcategorize_plan_card(e, []) == "Payoff"
    ]

    # Earliest realistic deployment turns
    # With ramp: commander can come down 1 turn early per ramp piece (rough heuristic)
    ramp_bonus = min(ramp_count // 4, 2)  # each 4 ramp pieces shave ~1 turn
    earliest_cmd_turn = max(1, int(cmd_cmc or 4) - ramp_bonus)

    # Are there low-CMC payoffs that can close out a game independently?
    low_cmc_payoffs = [e for e in payoff_cards if (e.cmc or 0) <= 4]
    high_cmc_finishers = [e for e in payoff_cards if (e.cmc or 0) >= 5]

    has_path = bool(low_cmc_payoffs or (cmd_cmc and cmd_cmc <= 5))

    # Assess confidence
    if ramp_count >= 10 and len(payoff_cards) >= 6:
        confidence = "High"
        summary = (
            f"Strong path to victory. With {ramp_count} ramp pieces, {cmd_name} "
            f"can land on turn {earliest_cmd_turn}. {len(low_cmc_payoffs)} low-cost "
            "payoffs can apply pressure before or after."
        )
    elif ramp_count >= 6 and len(payoff_cards) >= 3:
        confidence = "Medium"
        summary = (
            f"Reasonable path to victory. Aim to land {cmd_name} by turn "
            f"{earliest_cmd_turn} and follow up with a payoff by turn 5. "
            f"{len(payoff_cards)} payoffs detected ({len(low_cmc_payoffs)} at CMC 4 or less)."
        )
    else:
        confidence = "Low"
        summary = (
            f"Unclear path to victory by turn 5. Ramp count ({ramp_count}) "
            f"and payoff density ({len(payoff_cards)}) may leave the deck without "
            "a meaningful threat in the first 5 turns. Add more ramp and low-CMC payoffs."
        )

    return {
        "confidence": confidence,
        "summary": summary,
        "commander_earliest_turn": earliest_cmd_turn,
        "low_cmc_payoffs": [e.name for e in low_cmc_payoffs[:6]],
        "high_cmc_finishers": [e.name for e in high_cmc_finishers[:6]],
        "ramp_count": ramp_count,
        "payoff_count": len(payoff_cards),
    }


# ─── Playtesting simulation ───────────────────────────────────────────────────

def simulate_playtest(entries: list[CardEntry], multi_roles: dict[str, list[str]]) -> dict:
    """
    Simulate the expected hand quality over a 5–7 turn window.
    Uses expected value (hypergeometric approximation):
      E[category hits in N draws] = (category_count / deck_size) * N

    Checks:
      - Do you see enough ramp in the first 7 turns (opening + 6 draws)?
      - Do you see a card advantage engine early enough?
      - Do you hit land drops consistently?
      - Do you run out of cards? (card advantage check)
    """
    found = [e for e in entries if e.found]
    deck_size = sum(e.quantity for e in found)
    if not deck_size:
        return {"error": "No cards found in deck."}

    # Category counts
    cat_counts: dict[str, int] = defaultdict(int)
    for e in found:
        roles = multi_roles.get(e.name or "", [])
        for r in roles:
            cat_counts[r] += e.quantity

    def expected(cat: str, draws: int) -> float:
        return round((cat_counts.get(cat, 0) / deck_size) * draws, 1)

    opening = 7
    turn5  = opening + 5   # 12 cards seen
    turn7  = opening + 7   # 14 cards seen

    results = {
        "opening_hand": {},
        "by_turn_5": {},
        "by_turn_7": {},
        "assessments": [],
    }

    for cat in ["Lands", "Ramp", "Card Advantage", "Removal", "Plan Cards"]:
        results["opening_hand"][cat]  = expected(cat, opening)
        results["by_turn_5"][cat]     = expected(cat, turn5)
        results["by_turn_7"][cat]     = expected(cat, turn7)

    assessments = []

    # Land drops: want 3–4 in opening hand
    land_opening = results["opening_hand"]["Lands"]
    if land_opening < 2.8:
        assessments.append(
            f"Low expected lands in opening hand ({land_opening}). "
            "You will mulligan frequently. Consider more lands or mana rocks."
        )
    elif land_opening > 4.0:
        assessments.append(
            f"High expected lands in opening ({land_opening}). "
            "You may flood often — consider trimming 1–2 lands."
        )
    else:
        assessments.append(
            f"Land drops look solid: ~{land_opening} lands expected in opening hand."
        )

    # Ramp: want at least 1 by turn 3 (in hand by opening or turn 1-2)
    ramp_opening = results["opening_hand"]["Ramp"]
    if ramp_opening < 0.8:
        assessments.append(
            f"Only ~{ramp_opening} ramp pieces expected in opening hand. "
            "Add more 1–2 CMC ramp to reliably accelerate."
        )
    else:
        assessments.append(
            f"~{ramp_opening} ramp pieces expected in opening hand — good early acceleration."
        )

    # Card advantage: want an engine by turn 5
    ca_t5 = results["by_turn_5"]["Card Advantage"]
    if ca_t5 < 1.2:
        assessments.append(
            f"Only ~{ca_t5} card advantage pieces expected by turn 5. "
            "You risk running out of cards by mid-game. Add more draw engines."
        )
    else:
        assessments.append(
            f"~{ca_t5} card advantage pieces seen by turn 5 — card velocity looks healthy."
        )

    # Plan cards: want 2–3 by turn 5 to feel the strategy
    plan_t5 = results["by_turn_5"]["Plan Cards"]
    if plan_t5 < 2.0:
        assessments.append(
            f"Only ~{plan_t5} plan cards expected by turn 5. "
            "The strategy may not feel cohesive in a 5-turn window."
        )
    else:
        assessments.append(
            f"~{plan_t5} plan cards by turn 5 — the game plan should be visible early."
        )

    results["assessments"] = assessments
    results["category_counts"] = dict(cat_counts)
    return results


# ─── Mulligan guide ───────────────────────────────────────────────────────────

def mulligan_guide(entries: list[CardEntry], multi_roles: dict[str, list[str]]) -> dict:
    """
    Identify the engine pieces you want in your opening hand and build a keep/mulligan guide.
    """
    found = [e for e in entries if e.found and not e.is_commander]

    # Engine pieces = Card Advantage cards at CMC ≤ 4 (can be cast in first few turns)
    engines = [
        e.name for e in found
        if "Card Advantage" in multi_roles.get(e.name or "", [])
        and (e.cmc or 0) <= 4
    ]

    # Key ramp (CMC ≤ 2 — early ramp)
    early_ramp = [
        e.name for e in found
        if "Ramp" in multi_roles.get(e.name or "", [])
        and (e.cmc or 0) <= 2
    ]

    commanders = [e for e in entries if e.is_commander]
    cmd = commanders[0] if commanders else None
    cmd_cmc = int(cmd.cmc or 4) if cmd else 4

    # Ideal hand profile
    ideal_hand = []
    ideal_hand.append(f"3–4 lands (minimum 3 to hit your first drops reliably)")
    if early_ramp:
        ideal_hand.append(f"1 early ramp piece (e.g. {', '.join(early_ramp[:3])})")
    if engines:
        ideal_hand.append(f"1 card advantage engine (e.g. {', '.join(engines[:3])})")
    if cmd and cmd_cmc <= 5:
        ideal_hand.append(
            f"Optional: {cmd.name} ({cmd_cmc} CMC) or a way to protect it"
        )

    # Mulligan triggers
    mulligan_away = [
        "Fewer than 2 lands",
        "No ramp or acceleration and a slow curve",
        "All cards CMC 5+ with no way to survive early turns",
    ]

    return {
        "engine_pieces": engines[:10],
        "early_ramp_pieces": early_ramp[:10],
        "ideal_hand_profile": ideal_hand,
        "mulligan_triggers": mulligan_away,
    }


# ─── Sequencing guide ─────────────────────────────────────────────────────────

def sequencing_guide(entries: list[CardEntry], commander_roles: list[str]) -> list[dict]:
    """
    Produce a turn-by-turn sequencing template based on the commander's role
    and the cards available at each CMC.
    """
    found = [e for e in entries if e.found and not e.is_commander]
    commanders = [e for e in entries if e.is_commander]
    cmd = commanders[0] if commanders else None

    by_cmc: dict[int, list[str]] = defaultdict(list)
    for e in found:
        cmc = int(e.cmc or 0)
        by_cmc[cmc].append(e.name)

    def pick(cmc: int, n: int = 2) -> str:
        cards = by_cmc.get(cmc, [])
        if not cards:
            return f"[no {cmc}-CMC cards]"
        sample = cards[:n]
        return ", ".join(sample) + ("…" if len(cards) > n else "")

    guide = [
        {
            "turn": 1,
            "priority": "Land drop",
            "notes": f"Play a land. If possible, play a 1-CMC ramp piece ({pick(1)}) or leave up interaction.",
        },
        {
            "turn": 2,
            "priority": "Ramp or rock",
            "notes": f"Play your most impactful 2-CMC ramp piece ({pick(2)}). Getting ahead on mana is critical.",
        },
        {
            "turn": 3,
            "priority": "Engine or early value",
            "notes": f"Land a card-draw engine or key enabler ({pick(3)}). If ramp is ahead of schedule, consider dropping a 4-CMC piece early.",
        },
        {
            "turn": 4,
            "priority": f"Commander ({cmd.name}, {int(cmd.cmc or 0)} CMC) or 4-drop" if cmd and (cmd.cmc or 0) <= 4 else "4-drop value piece",
            "notes": (
                f"Deploy {cmd.name} if safe, protecting it with instant-speed removal or a counter." if cmd and (cmd.cmc or 0) <= 4
                else f"Play a 4-CMC value piece ({pick(4)}) and hold mana for interaction."
            ),
        },
        {
            "turn": 5,
            "priority": "First payoff / threat",
            "notes": f"Your plan should be visible by now. Deploy your first payoff ({pick(5, 3)}) or activate a win condition. If behind, stabilize with a boardwipe.",
        },
        {
            "turn": "5–7",
            "priority": "Execute the plan",
            "notes": (
                f"The deck's strategy should be in motion. Commander role targets: {', '.join(commander_roles) or 'none set'}. "
                "Use card advantage to refuel. Protect key pieces. Apply pressure or close out the game."
            ),
        },
    ]

    # Insert commander on correct turn if CMC > 4
    if cmd and (cmd.cmc or 0) > 4:
        cmd_turn = int(cmd.cmc or 5)
        guide.append({
            "turn": cmd_turn,
            "priority": f"Commander — {cmd.name}",
            "notes": f"Land {cmd.name} ({int(cmd.cmc)} CMC). By this point your ramp should enable it. Protect immediately with Lightning Greaves/Swiftfoot Boots if possible.",
        })
        guide.sort(key=lambda x: x["turn"] if isinstance(x["turn"], int) else 99)

    return guide


# ─── Coverage summary ─────────────────────────────────────────────────────────

def coverage_summary(
    entries: list[CardEntry],
    multi_roles: dict[str, list[str]],
) -> dict:
    """
    Tally how many cards (by quantity) cover each framework category,
    accounting for overlap (a card covering two categories still occupies one slot).
    """
    cat_totals: Counter = Counter()
    overlap_cards: list[str] = []

    for entry in entries:
        if not entry.found:
            continue
        roles = multi_roles.get(entry.name or "", [])
        for r in roles:
            cat_totals[r] += entry.quantity
        if len(roles) > 1:
            overlap_cards.append(entry.name or entry.raw_name)

    result = {}
    for cat, target in TARGETS.items():
        actual = cat_totals.get(cat, 0)
        pct = round((actual / target) * 100) if target else 0
        status = "ok" if actual >= target else ("close" if actual >= target * 0.8 else "low")
        result[cat] = {
            "actual": actual,
            "target": target,
            "pct": pct,
            "status": status,
            "delta": actual - target,
        }

    return {
        "categories": result,
        "overlap_cards": overlap_cards[:20],
        "overlap_count": len(overlap_cards),
        "note": (
            f"{len(overlap_cards)} card(s) cover multiple categories, "
            "compressing slot usage. This is intentional — aim for 8–10 overlap cards."
        ),
    }


# ─── Main entry point ─────────────────────────────────────────────────────────

def analyze_plan(
    entries: list[CardEntry],
    color_identity: list[str] | None = None,
    commander_roles_override: list[str] | None = None,
) -> dict:
    """
    Run the full plan analysis and return a structured result dict.
    color_identity: list of color codes for the commander (e.g. ["U", "B"]).
    """
    found = [e for e in entries if e.found]

    # Multi-role tagging for all cards
    multi_roles: dict[str, list[str]] = {
        e.name: assign_roles(e)
        for e in found
        if e.name
    }

    # Plan card sub-classification
    commanders = [e for e in found if e.is_commander]
    detected_role_matches = detect_commander_role_matches(commanders[0], found) if commanders else [{
        "name": "Unknown",
        "kind": "theme",
        "score": 0,
        "confidence": "low",
        "description": "No commander was detected for this deck.",
        "evidence": ["no commander found"],
        "deck_count": 0,
    }]
    detected_commander_roles = [match["name"] for match in detected_role_matches]
    has_role_override = commander_roles_override is not None
    cleaned_override = [r.strip() for r in (commander_roles_override or []) if r and r.strip()]
    commander_roles = cleaned_override if has_role_override else detected_commander_roles
    commander_role_details = []
    detected_by_name = {match["name"].lower(): match for match in detected_role_matches}
    for role in commander_roles:
        detected_match = detected_by_name.get(role.lower())
        if detected_match:
            commander_role_details.append(detected_match)
            continue
        meta = get_role_metadata(role)
        commander_role_details.append({
            "name": role,
            "kind": meta.get("kind", "custom") if meta else "custom",
            "score": None,
            "confidence": None,
            "description": meta.get("description", _role_description(role)) if meta else _role_description(role),
            "evidence": ["user-selected target role"] if has_role_override else [],
            "deck_count": meta.get("deck_count", 0) if meta else 0,
        })
    focus_advice = commander_focus_advice(commander_roles, color_identity=color_identity)

    plan_subcategories: dict[str, str] = {}
    for e in found:
        if "Plan Cards" in multi_roles.get(e.name or "", []):
            plan_subcategories[e.name] = subcategorize_plan_card(e, commander_roles)

    # Coverage
    coverage = coverage_summary(entries, multi_roles)

    # Curve
    curve = evaluate_curve(entries)

    # Path to victory
    ptv = path_to_victory(entries, multi_roles)

    # Playtest simulation
    playtest = simulate_playtest(entries, multi_roles)

    # Mulligan guide
    mulligan = mulligan_guide(entries, multi_roles)

    # Sequencing
    sequencing = sequencing_guide(entries, commander_roles)

    # Build per-card role map for the response
    card_roles = []
    for e in found:
        roles = multi_roles.get(e.name or "", [])
        sub = plan_subcategories.get(e.name or "")
        card_roles.append({
            "name": e.name,
            "roles": roles,
            "plan_subcategory": sub,
            "is_overlap": len(roles) > 1,
        })

    return {
        "commander_roles": commander_roles,
        "detected_commander_roles": detected_commander_roles,
        "commander_role_details": commander_role_details,
        "detected_commander_role_matches": detected_role_matches,
        "commander_roles_source": "user" if has_role_override else "detected",
        "commander_focus_advice": focus_advice,
        "coverage": coverage,
        "curve_evaluation": curve,
        "path_to_victory": ptv,
        "playtest_simulation": playtest,
        "mulligan_guide": mulligan,
        "sequencing_guide": sequencing,
        "card_roles": card_roles,
        "plan_subcategories": plan_subcategories,
    }
