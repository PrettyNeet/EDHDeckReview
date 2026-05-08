"""
Bracket evaluator agent.
Assigns a Commander bracket (1-5) based on the official Commander bracket system:

Bracket 1 (Exhibition)  — Theme/fun decks; no GC, no extra turns, no combos
Bracket 2 (Core)        — Mechanically focused; no GC, no MLD, no chaining extra turns, no combos
Bracket 3 (Upgraded)    — Strong synergy; up to 3 GC, no MLD, no extra-turn chains, no early combos
Bracket 4 (Optimized)   — Powerful, consistent, lethal; no restrictions beyond ban list
Bracket 5 (cEDH)        — Meticulously built for the cEDH metagame; wins quickly, no margin for error

The Scryfall `game_changer` field maps directly to the bracket criteria.
"""

from __future__ import annotations
import re
from app.models.card import CardEntry, BracketAssessment

# ─── Fast mana (Bracket 4-5 markers) ──────────────────────────────────────────
FAST_MANA_CARDS = {
    "Mana Crypt", "Mana Vault", "Chrome Mox", "Mox Diamond",
    "Jeweled Lotus", "Lotus Petal", "Ancient Tomb",
    "Grim Monolith", "Mox Opal", "Mox Amber",
    "Lion's Eye Diamond", "Mishra's Workshop",
    "Black Lotus", "Mox Sapphire", "Mox Ruby", "Mox Pearl",
    "Mox Jet", "Mox Emerald",
}

# ─── Extra turns ───────────────────────────────────────────────────────────────
EXTRA_TURN_PATTERN = re.compile(
    r"take an extra turn|additional turn|takes an extra turn", re.IGNORECASE
)
EXTRA_COMBAT_PATTERN = re.compile(
    r"additional combat phase|an additional combat", re.IGNORECASE
)

# ─── Mass land destruction (pushes to Bracket 3+ in Upgraded, not allowed below) ─
MLD_CARDS = {
    "Armageddon", "Ravages of War", "Jokulhaups", "Obliterate",
    "Catastrophe", "Boom // Bust", "Wildfire", "Decree of Annihilation",
    "Ruination", "Fall of the Thran",
}

# ─── Heavy stax ────────────────────────────────────────────────────────────────
STAX_PATTERN = re.compile(
    r"players can't (cast|play|draw)|"
    r"each player skips|"
    r"spells cost.*more to cast|"
    r"opponents can't cast|"
    r"can't (be cast|untap)",
    re.IGNORECASE,
)

# ─── Two-card combo heuristics ────────────────────────────────────────────────
COMBO_PAIRS = [
    frozenset({"Dramatic Reversal", "Isochron Scepter"}),
    frozenset({"Basalt Monolith", "Rings of Brighthearth"}),
    frozenset({"Deadeye Navigator", "Palinchron"}),
    frozenset({"Nim Deathmantle", "Ashnod's Altar"}),
    frozenset({"Thassa's Oracle", "Demonic Consultation"}),
    frozenset({"Thassa's Oracle", "Tainted Pact"}),
    frozenset({"Laboratory Maniac", "Demonic Consultation"}),
    frozenset({"Laboratory Maniac", "Tainted Pact"}),
    frozenset({"Exquisite Blood", "Sanguine Bond"}),
    frozenset({"Heliod, Sun-Crowned", "Walking Ballista"}),
    frozenset({"Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"}),
    frozenset({"Mikaeus, the Unhallowed", "Triskelion"}),
]

EARLY_COMBO_PAIRS = {
    frozenset({"Dramatic Reversal", "Isochron Scepter"}),
    frozenset({"Thassa's Oracle", "Demonic Consultation"}),
    frozenset({"Thassa's Oracle", "Tainted Pact"}),
    frozenset({"Laboratory Maniac", "Demonic Consultation"}),
    frozenset({"Laboratory Maniac", "Tainted Pact"}),
    frozenset({"Heliod, Sun-Crowned", "Walking Ballista"}),
}

# ─── Known cEDH commanders ────────────────────────────────────────────────────
CEDH_COMMANDERS = {
    "Tymna the Weaver", "Thrasios, Triton Hero", "Kenrith, the Returned King",
    "Najeela, the Blade-Blossom", "Rofellos, Llanowar Emissary",
    "Tevita, Depths of Deception", "Kinnan, Bonder Prodigy",
    "Sisay, Weatherlight Captain", "Urza, Lord High Artificer",
    "Inalla, Archmage Ritualist", "Gitrog Monster",
    "Kraum, Ludevic's Opus", "Reyhan, Last of the Abzan",
}

BRACKET_LABELS = {
    1: "Exhibition",
    2: "Core",
    3: "Upgraded",
    4: "Optimized",
    5: "cEDH",
}

BRACKET_DESCRIPTIONS = {
    1: "Theme/fun deck. No Game Changers, no extra turns, no mass land denial, no two-card combos. Expect 9+ turns.",
    2: "Mechanically focused. No Game Changers, no MLD, no chaining extra turns, no two-card combos. Expect 8+ turns.",
    3: "Powered-up synergy. Up to 3 Game Changers allowed. No MLD, no extra-turn chains, no early two-card combos. Expect 6+ turns.",
    4: "Lethal and consistent. No restrictions beyond the ban list. Not adherent to the cEDH metagame. Expect 4+ turns.",
    5: "cEDH. Meticulously built for the competitive metagame using known tools and lists. Wins quickly on any turn.",
}


def evaluate(entries: list[CardEntry], intended_bracket: int | None = None) -> BracketAssessment:
    """
    Evaluate the deck's power bracket (1–5).
    `intended_bracket` triggers mismatch notes if the computed bracket differs.
    """
    found = [e for e in entries if e.found]
    names = {(e.name or "").strip() for e in found}

    # ── Game changers ─────────────────────────────────────────────────────
    game_changers = [e for e in found if e.game_changer]
    gc_count = len(game_changers)
    gc_names = [e.name for e in game_changers]

    # ── Fast mana ─────────────────────────────────────────────────────────
    fast_mana = [n for n in names if n in FAST_MANA_CARDS]
    fast_mana_count = len(fast_mana)

    # ── Extra turns ────────────────────────────────────────────────────────
    extra_turns = [e.name for e in found if EXTRA_TURN_PATTERN.search(e.oracle_text or "")]
    extra_combat = [e.name for e in found if EXTRA_COMBAT_PATTERN.search(e.oracle_text or "")]

    # ── Mass land destruction ─────────────────────────────────────────────
    mld = [n for n in names if n in MLD_CARDS]

    # ── Stax ──────────────────────────────────────────────────────────────
    stax = [e.name for e in found if STAX_PATTERN.search(e.oracle_text or "")]

    # ── Combo heuristic ───────────────────────────────────────────────────
    completed_combos = [pair for pair in COMBO_PAIRS if pair.issubset(names)]
    combo_cards = sorted({card for pair in completed_combos for card in pair})
    combo_piece_count = len(combo_cards)
    early_combo_count = sum(1 for pair in completed_combos if pair in EARLY_COMBO_PAIRS)
    if len(completed_combos) >= 2:
        combo_potential = "high"
    elif len(completed_combos) == 1:
        combo_potential = "medium"
    else:
        combo_potential = "none"

    # ── cEDH commander check ──────────────────────────────────────────────
    commanders = [e for e in entries if e.is_commander]
    is_cedh_commander = any(c.name in CEDH_COMMANDERS for c in commanders if c.name)

    # ── Bracket assignment ────────────────────────────────────────────────
    reasoning: list[str] = []

    # Bracket 5 (cEDH): Known cEDH commander or meticulously tuned (heavy fast mana + high combo)
    if is_cedh_commander or (fast_mana_count >= 3 and (combo_potential == "high" or early_combo_count >= 1)):
        bracket = 5
        if is_cedh_commander:
            reasoning.append("Commander is a recognized cEDH archetype pick.")
        if fast_mana_count >= 3:
            reasoning.append(f"{fast_mana_count} fast-mana pieces ({', '.join(fast_mana)}) indicate cEDH-level optimization.")
        if early_combo_count >= 1 or combo_potential == "high":
            reasoning.append(
                f"Fast mana plus {early_combo_count or len(completed_combos)} completed two-card combo package(s) indicates cEDH-level optimization."
            )

    # Bracket 4 (Optimized): 4+ GC, meaningful fast mana + strong build, or full combo package
    elif gc_count > 3 or (fast_mana_count >= 2 and gc_count >= 2) or combo_potential == "high" or early_combo_count >= 1:
        bracket = 4
        if gc_count > 3:
            reasoning.append(f"{gc_count} Game Changer card(s) exceed the Bracket 3 limit of 3.")
        if fast_mana_count >= 2:
            reasoning.append(f"{fast_mana_count} fast-mana pieces ({', '.join(fast_mana)}).")
        if combo_potential == "high":
            reasoning.append(
                f"Multiple completed two-card combos detected ({'; '.join(' + '.join(sorted(pair)) for pair in completed_combos[:3])})."
            )
        elif early_combo_count >= 1:
            reasoning.append(
                f"Early two-card combo package detected ({'; '.join(' + '.join(sorted(pair)) for pair in completed_combos[:2])})."
            )

    # Bracket 3 (Upgraded): 1–3 GC, non-early completed combo, fast mana, or extra turns
    elif gc_count >= 1 or combo_potential == "medium" or fast_mana_count >= 1 or extra_turns or mld:
        bracket = 3
        if gc_count:
            reasoning.append(f"{gc_count} Game Changer card(s) detected (Bracket 3 allows up to 3).")
        if combo_potential == "medium":
            reasoning.append(
                f"Completed two-card combo present ({'; '.join(' + '.join(sorted(pair)) for pair in completed_combos[:2])}), but not at the early-game Bracket 4 threshold."
            )
        if fast_mana_count:
            reasoning.append(f"{fast_mana_count} fast-mana piece(s) ({', '.join(fast_mana)}).")
        if extra_turns:
            reasoning.append(f"Extra turn effects ({', '.join(extra_turns[:3])}) increase power level.")
        if mld:
            reasoning.append(f"Mass land denial ({', '.join(mld)}) is not permitted below Bracket 3.")

    # Bracket 2 (Core): No GC, but single extra turn effects or stax are OK
    elif len(extra_turns) == 1 or (len(stax) >= 1 and gc_count == 0):
        bracket = 2
        if extra_turns:
            reasoning.append(f"Single extra turn effect ({extra_turns[0]}) — chaining would push to Bracket 3.")
        if stax:
            reasoning.append(f"{len(stax)} stax effect(s) noted — Bracket 2 allows light disruption.")

    # Bracket 1 (Exhibition): Clean build, no notable power cards
    else:
        bracket = 1
        reasoning.append("No Game Changers, no fast mana, no extra turns, no combo pieces.")
        reasoning.append("Deck plays at an Exhibition/Precon-comparable power level.")

    # ── Stax / MLD bumps ─────────────────────────────────────────────────
    if mld and bracket < 3:
        reasoning.append(f"Mass land denial bumps bracket to at least 3.")
        bracket = max(bracket, 3)
    if len(stax) >= 3 and bracket < 3:
        reasoning.append(f"{len(stax)} stax effects suggest Bracket 3 minimum.")
        bracket = max(bracket, 3)

    # ── Intended bracket mismatch ─────────────────────────────────────────
    if intended_bracket and intended_bracket != bracket:
        if intended_bracket < bracket:
            reasoning.append(
                f"⚠ You declared Bracket {intended_bracket} but analysis suggests Bracket {bracket}. "
                "Discuss with your playgroup."
            )
        else:
            reasoning.append(
                f"ℹ You declared Bracket {intended_bracket} but the deck plays closer to Bracket {bracket}. "
                "It may underperform at higher tables."
            )

    return BracketAssessment(
        bracket=bracket,
        label=BRACKET_LABELS[bracket],
        reasoning=reasoning,
        game_changer_count=gc_count,
        game_changer_cards=gc_names,
        fast_mana_count=fast_mana_count,
        combo_potential=combo_potential,
    )
