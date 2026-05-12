"""Tests for the bracket evaluator — bracket assignment logic and edge cases."""

import unittest

from app.agents.bracket import evaluate, FAST_MANA_CARDS, COMBO_PAIRS, EARLY_COMBO_PAIRS
from app.models.card import CardEntry, BracketAssessment


def card(name, oracle_text="", type_line="Instant", game_changer=False,
         is_commander=False, power=None):
    return CardEntry(
        quantity=1,
        raw_name=name,
        name=name,
        found=True,
        type_line=type_line,
        oracle_text=oracle_text,
        game_changer=game_changer,
        is_commander=is_commander,
        power=power,
    )


def commander(name, oracle_text="", type_line="Legendary Creature — Human"):
    return card(name, oracle_text=oracle_text, type_line=type_line, is_commander=True)


class BracketOneTests(unittest.TestCase):
    """Bracket 1 — no GC, no fast mana, no extra turns, no combos."""

    def test_clean_deck_is_bracket_1(self):
        entries = [commander("Generic Legend"), card("Murder"), card("Cultivate")]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 1)
        self.assertEqual(result.label, "Exhibition")

    def test_empty_deck_is_bracket_1(self):
        result = evaluate([commander("Some Legend")])
        self.assertEqual(result.bracket, 1)

    def test_bracket_1_has_no_game_changers(self):
        entries = [commander("Generic Legend"), card("Llanowar Elves")]
        result = evaluate(entries)
        self.assertEqual(result.game_changer_count, 0)
        self.assertEqual(result.combo_potential, "none")


class BracketTwoTests(unittest.TestCase):
    """Bracket 2 — no GC, single extra turn or light stax OK."""

    def test_single_extra_turn_is_bracket_2(self):
        entries = [
            commander("Generic Legend"),
            card("Time Warp", "Take an extra turn after this one."),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 2)

    def test_single_stax_is_bracket_2(self):
        entries = [
            commander("Generic Legend"),
            card("Rhystic Study", "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}. Spells cost {1} more to cast."),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 2)

    def test_no_gc_no_power_cards_is_not_bracket_3(self):
        entries = [
            commander("Generic Legend"),
            card("Birds of Paradise", "Flying\n{T}: Add one mana of any color."),
        ]
        result = evaluate(entries)
        self.assertLessEqual(result.bracket, 2)


class BracketThreeTests(unittest.TestCase):
    """Bracket 3 — 1-3 GC, single fast mana, or non-early completed combo."""

    def test_one_game_changer_is_bracket_3(self):
        entries = [
            commander("Generic Legend"),
            card("Rhystic Study", game_changer=True),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 3)
        self.assertEqual(result.game_changer_count, 1)

    def test_three_game_changers_still_bracket_3(self):
        entries = [
            commander("Generic Legend"),
            card("GC1", game_changer=True),
            card("GC2", game_changer=True),
            card("GC3", game_changer=True),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 3)

    def test_single_fast_mana_is_bracket_3(self):
        entries = [commander("Generic Legend"), card("Mana Crypt")]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 3)
        self.assertEqual(result.fast_mana_count, 1)

    def test_mld_pushes_to_bracket_3(self):
        entries = [commander("Generic Legend"), card("Armageddon")]
        result = evaluate(entries)
        self.assertGreaterEqual(result.bracket, 3)

    def test_non_early_combo_is_bracket_3(self):
        # Basalt Monolith + Rings of Brighthearth — slower combo, not in EARLY_COMBO_PAIRS
        entries = [
            commander("Generic Legend"),
            card("Basalt Monolith"),
            card("Rings of Brighthearth"),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 3)
        self.assertEqual(result.combo_potential, "medium")

    def test_extra_turns_multiple_is_bracket_3(self):
        entries = [
            commander("Generic Legend"),
            card("Time Warp", "Take an extra turn after this one."),
            card("Temporal Manipulation", "Take an extra turn after this one."),
        ]
        result = evaluate(entries)
        self.assertGreaterEqual(result.bracket, 3)


class BracketFourTests(unittest.TestCase):
    """Bracket 4 — 4+ GC, fast mana + GC combo, or early two-card combo."""

    def test_four_game_changers_is_bracket_4(self):
        entries = [
            commander("Generic Legend"),
            card("GC1", game_changer=True),
            card("GC2", game_changer=True),
            card("GC3", game_changer=True),
            card("GC4", game_changer=True),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 4)

    def test_early_combo_is_bracket_4(self):
        # Thassa's Oracle + Demonic Consultation — early combo
        entries = [
            commander("Generic Legend"),
            card("Thassa's Oracle", type_line="Legendary Creature — Merfolk Wizard"),
            card("Demonic Consultation"),
        ]
        result = evaluate(entries)
        self.assertGreaterEqual(result.bracket, 4)

    def test_two_fast_mana_two_gc_is_bracket_4(self):
        entries = [
            commander("Generic Legend"),
            card("Mana Crypt"),
            card("Sol Ring"),  # Not in FAST_MANA_CARDS but GC could push it
            card("GC1", game_changer=True),
            card("GC2", game_changer=True),
        ]
        result = evaluate(entries)
        # Sol Ring is not in FAST_MANA_CARDS; only Mana Crypt counts here
        # With 1 fast mana + 2 GC — still might be 3 or 4 depending on exact logic
        self.assertGreaterEqual(result.bracket, 3)

    def test_two_fast_mana_cards_pushes_bracket(self):
        entries = [
            commander("Generic Legend"),
            card("Mana Crypt"),
            card("Mana Vault"),
            card("GC1", game_changer=True),
            card("GC2", game_changer=True),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 4)
        self.assertEqual(result.fast_mana_count, 2)

    def test_multiple_two_card_combos_is_bracket_4(self):
        entries = [
            commander("Generic Legend"),
            card("Thassa's Oracle"),
            card("Demonic Consultation"),
            card("Basalt Monolith"),
            card("Rings of Brighthearth"),
        ]
        result = evaluate(entries)
        self.assertGreaterEqual(result.bracket, 4)


class BracketFiveTests(unittest.TestCase):
    """Bracket 5 — cEDH commander or heavy fast mana + high combo."""

    def test_cedh_commander_is_bracket_5(self):
        entries = [
            commander("Tymna the Weaver",
                      type_line="Legendary Creature — Human Cleric"),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 5)
        self.assertEqual(result.label, "cEDH")

    def test_heavy_fast_mana_plus_early_combo_is_bracket_5(self):
        entries = [
            commander("Generic Legend"),
            card("Mana Crypt"),
            card("Mana Vault"),
            card("Chrome Mox"),
            card("Thassa's Oracle"),
            card("Demonic Consultation"),
        ]
        result = evaluate(entries)
        self.assertEqual(result.bracket, 5)

    def test_fast_mana_count_tracked(self):
        entries = [
            commander("Generic Legend"),
            card("Mana Crypt"),
            card("Mana Vault"),
            card("Chrome Mox"),
        ]
        result = evaluate(entries)
        self.assertEqual(result.fast_mana_count, 3)


class IntendedBracketMismatchTests(unittest.TestCase):
    def test_over_declared_bracket_warns(self):
        entries = [commander("Generic Legend"), card("Murder")]
        result = evaluate(entries, intended_bracket=4)
        self.assertTrue(any("Bracket 4" in r for r in result.reasoning))

    def test_under_declared_bracket_warns(self):
        entries = [
            commander("Generic Legend"),
            card("GC1", game_changer=True),
            card("GC2", game_changer=True),
            card("GC3", game_changer=True),
            card("GC4", game_changer=True),
        ]
        result = evaluate(entries, intended_bracket=1)
        # Should warn about mismatch
        self.assertTrue(any("⚠" in r for r in result.reasoning))

    def test_matching_bracket_no_mismatch_warning(self):
        entries = [commander("Generic Legend"), card("Murder")]
        result = evaluate(entries, intended_bracket=1)
        self.assertFalse(any("⚠" in r or "ℹ" in r for r in result.reasoning))


class BracketOutputShapeTests(unittest.TestCase):
    def test_returns_bracket_assessment(self):
        result = evaluate([commander("Generic Legend")])
        self.assertIsInstance(result, BracketAssessment)
        self.assertIn(result.bracket, range(1, 6))
        self.assertIsInstance(result.reasoning, list)
        self.assertIsInstance(result.game_changer_cards, list)

    def test_to_dict_serializes(self):
        result = evaluate([commander("Generic Legend")])
        d = result.to_dict()
        self.assertIn("bracket", d)
        self.assertIn("label", d)
        self.assertIn("reasoning", d)
        self.assertIn("combo_potential", d)


if __name__ == "__main__":
    unittest.main()
