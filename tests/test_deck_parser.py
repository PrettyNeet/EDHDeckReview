"""Tests for deck_parser — parsing logic, commander detection, format variants."""

import unittest
from unittest.mock import patch

from app.agents.deck_parser import (
    parse_decklist_text,
    get_commanders,
    get_non_commander_entries,
    _parse_line,
)
from app.models.card import CardEntry


# ── Minimal Scryfall stub so tests don't need the local card index ─────────────

def _scryfall_stub(name: str):
    """Return a minimal card dict for well-known cards, None otherwise."""
    db = {
        "Atraxa, Praetors' Voice": {
            "name": "Atraxa, Praetors' Voice",
            "type_line": "Legendary Creature — Phyrexian Angel Horror",
            "oracle_text": "Flying, deathtouch, lifelink, vigilance\nAt the beginning of your end step, proliferate.",
            "color_identity": ["B", "G", "U", "W"],
            "colors": ["B", "G", "U", "W"],
            "cmc": 6.0,
            "power": "4",
            "toughness": "7",
            "keywords": ["Flying", "Deathtouch", "Lifelink", "Vigilance"],
            "legalities": {"commander": "legal"},
            "game_changer": False,
            "rarity": "mythic",
            "scryfall_uri": "https://scryfall.com/card/c21/1",
        },
        "Sol Ring": {
            "name": "Sol Ring",
            "type_line": "Artifact",
            "oracle_text": "{T}: Add {C}{C}.",
            "color_identity": [],
            "colors": [],
            "cmc": 1.0,
            "keywords": [],
            "legalities": {"commander": "legal"},
            "game_changer": False,
            "rarity": "uncommon",
        },
        "Rhystic Study": {
            "name": "Rhystic Study",
            "type_line": "Enchantment",
            "oracle_text": "Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.",
            "color_identity": ["U"],
            "colors": ["U"],
            "cmc": 3.0,
            "keywords": [],
            "legalities": {"commander": "legal"},
            "game_changer": True,
            "rarity": "common",
        },
        "Mountain": {
            "name": "Mountain",
            "type_line": "Basic Land — Mountain",
            "oracle_text": "",
            "color_identity": ["R"],
            "colors": [],
            "cmc": 0.0,
            "keywords": [],
            "legalities": {"commander": "legal"},
            "game_changer": False,
            "rarity": "land",
        },
        "Lightning Bolt": {
            "name": "Lightning Bolt",
            "type_line": "Instant",
            "oracle_text": "Lightning Bolt deals 3 damage to any target.",
            "color_identity": ["R"],
            "colors": ["R"],
            "cmc": 1.0,
            "keywords": [],
            "legalities": {"commander": "legal"},
            "game_changer": False,
            "rarity": "common",
        },
        "Thrasios, Triton Hero": {
            "name": "Thrasios, Triton Hero",
            "type_line": "Legendary Creature — Merfolk Wizard",
            "oracle_text": "{4}: Scry 1, then reveal the top card of your library. If it's a land, put it onto the battlefield. Otherwise, draw a card.\nPartner",
            "color_identity": ["G", "U"],
            "colors": ["G", "U"],
            "cmc": 2.0,
            "keywords": ["Partner"],
            "legalities": {"commander": "legal"},
            "game_changer": False,
            "rarity": "rare",
        },
        "Tymna the Weaver": {
            "name": "Tymna the Weaver",
            "type_line": "Legendary Creature — Human Cleric",
            "oracle_text": "Lifelink\nAt the beginning of your postcombat main phase, you may pay X life, where X is the number of opponents that were dealt combat damage this turn. If you do, draw X cards.\nPartner",
            "color_identity": ["B", "W"],
            "colors": ["B", "W"],
            "cmc": 3.0,
            "keywords": ["Lifelink", "Partner"],
            "legalities": {"commander": "legal"},
            "game_changer": False,
            "rarity": "rare",
        },
    }
    return db.get(name)


class ParseLineTests(unittest.TestCase):
    def test_plain_qty_name(self):
        self.assertEqual(_parse_line("1 Sol Ring"), (1, "Sol Ring"))

    def test_x_suffix(self):
        self.assertEqual(_parse_line("4x Mountain"), (4, "Mountain"))

    def test_uppercase_X(self):
        self.assertEqual(_parse_line("1X Rhystic Study"), (1, "Rhystic Study"))

    def test_leading_whitespace(self):
        self.assertEqual(_parse_line("  2 Lightning Bolt"), (2, "Lightning Bolt"))

    def test_double_faced_card_name(self):
        result = _parse_line("1 Ajani, Nacatl Pariah // Ajani, Nacatl Avenger")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 1)
        self.assertIn("Ajani", result[1])

    def test_no_quantity_returns_none(self):
        self.assertIsNone(_parse_line("Sol Ring"))

    def test_empty_line_returns_none(self):
        self.assertIsNone(_parse_line(""))

    def test_comment_line_returns_none(self):
        self.assertIsNone(_parse_line("// This is a comment"))


class CommanderDetectionTests(unittest.TestCase):
    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_explicit_commander_tag(self, _mock):
        text = "Commander: Atraxa, Praetors' Voice\n1 Atraxa, Praetors' Voice\n1 Sol Ring"
        entries = parse_decklist_text(text)
        commanders = get_commanders(entries)
        self.assertEqual(len(commanders), 1)
        self.assertEqual(commanders[0].name, "Atraxa, Praetors' Voice")

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_commander_hint_overrides_auto_detect(self, _mock):
        text = "1 Atraxa, Praetors' Voice\n1 Sol Ring"
        entries = parse_decklist_text(text, commander_hint="Sol Ring")
        commanders = get_commanders(entries)
        # Sol Ring is not legendary but hint should try to match by name
        # Atraxa should NOT be flagged since hint takes priority
        atraxa = next((e for e in entries if e.name == "Atraxa, Praetors' Voice"), None)
        sol = next((e for e in entries if e.name == "Sol Ring"), None)
        self.assertIsNotNone(atraxa)
        self.assertFalse(atraxa.is_commander)
        self.assertTrue(sol.is_commander)

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_auto_detect_skips_non_legendary(self, _mock):
        text = "1 Sol Ring\n1 Atraxa, Praetors' Voice"
        entries = parse_decklist_text(text)
        commanders = get_commanders(entries)
        # Sol Ring is first but can't be a commander — Atraxa should be detected
        self.assertEqual(len(commanders), 1)
        self.assertEqual(commanders[0].name, "Atraxa, Praetors' Voice")

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_partner_commanders_both_flagged(self, _mock):
        text = (
            "Commander: Thrasios, Triton Hero\n"
            "Commander: Tymna the Weaver\n"
            "1 Thrasios, Triton Hero\n"
            "1 Tymna the Weaver\n"
            "1 Sol Ring"
        )
        entries = parse_decklist_text(text)
        commanders = get_commanders(entries)
        self.assertEqual(len(commanders), 2)
        names = {c.name for c in commanders}
        self.assertIn("Thrasios, Triton Hero", names)
        self.assertIn("Tymna the Weaver", names)


class SkipLineTests(unittest.TestCase):
    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_comment_lines_skipped(self, _mock):
        text = "// Lands section\n1 Mountain"
        entries = parse_decklist_text(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].raw_name, "Mountain")

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_hash_comment_skipped(self, _mock):
        text = "# This is a comment\n1 Sol Ring"
        entries = parse_decklist_text(text)
        self.assertEqual(len(entries), 1)

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_sideboard_lines_skipped(self, _mock):
        text = "1 Sol Ring\nSB: 1 Rhystic Study"
        entries = parse_decklist_text(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].raw_name, "Sol Ring")

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_blank_lines_skipped(self, _mock):
        text = "1 Sol Ring\n\n\n1 Mountain"
        entries = parse_decklist_text(text)
        self.assertEqual(len(entries), 2)


class ScryfallEnrichmentTests(unittest.TestCase):
    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_found_card_enriched(self, _mock):
        entries = parse_decklist_text("1 Sol Ring")
        self.assertTrue(entries[0].found)
        self.assertEqual(entries[0].name, "Sol Ring")
        self.assertEqual(entries[0].cmc, 1.0)

    @patch("app.agents.deck_parser.lookup", return_value=None)
    def test_unknown_card_flagged(self, _mock):
        entries = parse_decklist_text("1 FakeCardThatDoesNotExist")
        self.assertFalse(entries[0].found)
        self.assertIsNotNone(entries[0].error)

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_quantity_preserved(self, _mock):
        entries = parse_decklist_text("4 Mountain")
        self.assertEqual(entries[0].quantity, 4)

    @patch("app.agents.deck_parser.lookup", side_effect=_scryfall_stub)
    def test_game_changer_flag_set(self, _mock):
        entries = parse_decklist_text("1 Rhystic Study")
        self.assertTrue(entries[0].game_changer)


class HelperFunctionTests(unittest.TestCase):
    def _make_entry(self, name, is_commander=False):
        e = CardEntry(quantity=1, raw_name=name, name=name, found=True,
                      type_line="Creature", oracle_text="", is_commander=is_commander)
        return e

    def test_get_commanders_filters_correctly(self):
        entries = [
            self._make_entry("Commander A", is_commander=True),
            self._make_entry("Card B"),
            self._make_entry("Card C"),
        ]
        self.assertEqual(len(get_commanders(entries)), 1)
        self.assertEqual(get_commanders(entries)[0].name, "Commander A")

    def test_get_non_commander_entries(self):
        entries = [
            self._make_entry("Commander A", is_commander=True),
            self._make_entry("Card B"),
        ]
        non_cmd = get_non_commander_entries(entries)
        self.assertEqual(len(non_cmd), 1)
        self.assertEqual(non_cmd[0].name, "Card B")


if __name__ == "__main__":
    unittest.main()
