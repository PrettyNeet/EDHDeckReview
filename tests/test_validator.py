"""Tests for the validator agent — Commander format rule enforcement."""

import unittest

from app.agents.validator import validate, get_commander_color_identity
from app.models.card import CardEntry, ValidationResult


def card(name, type_line="Instant", oracle_text="", color_identity=None,
         is_commander=False, quantity=1, legalities=None, found=True,
         game_changer=False, power=None):
    return CardEntry(
        quantity=quantity,
        raw_name=name,
        name=name,
        found=found,
        type_line=type_line,
        oracle_text=oracle_text,
        color_identity=color_identity or [],
        game_changer=game_changer,
        is_commander=is_commander,
        legalities=legalities or {"commander": "legal"},
        power=power,
    )


def legendary_creature(name, color_identity=None, oracle_text="", quantity=1):
    return card(
        name,
        type_line="Legendary Creature — Human",
        color_identity=color_identity or [],
        oracle_text=oracle_text,
        is_commander=True,
        quantity=quantity,
    )


# ── Helpers to build minimal valid decks ──────────────────────────────────────

def _make_deck(commander_card, fill_cards=None, total=100):
    """Build a list of entries that sums to `total` cards."""
    entries = [commander_card]
    if fill_cards:
        entries.extend(fill_cards)
    # Top up with basic plains (exempt from singleton)
    current = sum(e.quantity for e in entries)
    if total > current:
        plains = card("Plains", type_line="Basic Land — Plains",
                      color_identity=["W"], quantity=total - current)
        entries.append(plains)
    return entries


class CommanderPresenceTests(unittest.TestCase):
    def test_no_commander_gives_error(self):
        entries = [card("Sol Ring")]
        result = validate(entries)
        self.assertFalse(result.valid)
        self.assertTrue(any("No commander" in e for e in result.errors))

    def test_too_many_commanders_gives_error(self):
        entries = [
            legendary_creature("A"),
            legendary_creature("B"),
            legendary_creature("C"),
        ]
        result = validate(entries)
        self.assertFalse(result.valid)
        self.assertTrue(any("Too many commanders" in e for e in result.errors))

    def test_not_found_commander_gives_error(self):
        cmd = card("Unknown Legend", type_line="Legendary Creature — Human",
                   is_commander=True, found=False)
        result = validate([cmd])
        self.assertFalse(result.valid)
        self.assertTrue(any("not found" in e.lower() for e in result.errors))


class CardCountTests(unittest.TestCase):
    def test_exactly_100_cards_no_count_error(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        entries = _make_deck(cmd, total=100)
        result = validate(entries)
        self.assertFalse(any("100" in e for e in result.errors))

    def test_99_cards_gives_count_error(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        entries = _make_deck(cmd, total=99)
        result = validate(entries)
        self.assertTrue(any("99" in e for e in result.errors))

    def test_101_cards_gives_count_error(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        entries = _make_deck(cmd, total=101)
        result = validate(entries)
        self.assertTrue(any("101" in e for e in result.errors))


class SingletonTests(unittest.TestCase):
    def test_duplicate_non_basic_gives_error(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        dupe = card("Sol Ring", quantity=2, color_identity=[])
        entries = _make_deck(cmd, fill_cards=[dupe], total=100)
        result = validate(entries)
        self.assertTrue(any("Sol Ring" in e and "singleton" in e.lower() for e in result.errors))

    def test_basic_land_allows_multiple(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        many_plains = card("Plains", type_line="Basic Land — Plains",
                           color_identity=["W"], quantity=38)
        entries = [cmd, many_plains]
        # Pad to 100
        padding = card("Island", type_line="Basic Land — Island",
                       color_identity=["U"], quantity=61)
        entries.append(padding)
        result = validate(entries)
        self.assertFalse(any("Plains" in e and "singleton" in e.lower() for e in result.errors))


class ColorIdentityTests(unittest.TestCase):
    def test_off_color_card_gives_error(self):
        # Mono-W commander, blue card
        cmd = legendary_creature("Mono W Legend", color_identity=["W"])
        blue_card = card("Counterspell", color_identity=["U"])
        entries = _make_deck(cmd, fill_cards=[blue_card], total=100)
        result = validate(entries)
        self.assertTrue(any("Counterspell" in e for e in result.errors))

    def test_colorless_card_legal_in_any_deck(self):
        cmd = legendary_creature("Mono W Legend", color_identity=["W"])
        sol_ring = card("Sol Ring", color_identity=[])
        entries = _make_deck(cmd, fill_cards=[sol_ring], total=100)
        result = validate(entries)
        self.assertFalse(any("Sol Ring" in e and "color" in e.lower() for e in result.errors))

    def test_within_color_identity_is_valid(self):
        cmd = legendary_creature("5c Legend", color_identity=["W", "U", "B", "R", "G"])
        blue_card = card("Brainstorm", color_identity=["U"])
        entries = _make_deck(cmd, fill_cards=[blue_card], total=100)
        result = validate(entries)
        self.assertFalse(any("Brainstorm" in e for e in result.errors))

    def test_colorless_commander_warns(self):
        # Commander with no color identity
        cmd = card("Karn, Silver Golem", type_line="Legendary Artifact Creature — Golem",
                   color_identity=[], is_commander=True)
        result = validate([cmd])
        self.assertTrue(any("colorless" in w.lower() for w in result.warnings))


class LegalityTests(unittest.TestCase):
    def test_banned_card_gives_error(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        banned = card("Ancestral Recall", color_identity=["U"],
                      legalities={"commander": "banned"})
        entries = _make_deck(cmd, fill_cards=[banned], total=100)
        result = validate(entries)
        self.assertTrue(any("Ancestral Recall" in e and "banned" in e.lower() for e in result.errors))

    def test_not_legal_gives_error(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        not_legal = card("Unglued Card", color_identity=[],
                         legalities={"commander": "not_legal"})
        entries = _make_deck(cmd, fill_cards=[not_legal], total=100)
        result = validate(entries)
        self.assertTrue(any("not legal" in e.lower() for e in result.errors))

    def test_unknown_legality_gives_warning(self):
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        unknown = card("Mystery Card", color_identity=[],
                       legalities={"commander": "unknown"})
        entries = _make_deck(cmd, fill_cards=[unknown], total=100)
        result = validate(entries)
        self.assertTrue(any("Mystery Card" in w for w in result.warnings))

    def test_hardcoded_ban_list_card_gives_error(self):
        """Cards in the local BANNED_CARDS set should be caught even if Scryfall says legal."""
        cmd = legendary_creature("Atraxa", color_identity=["W", "U", "B", "G"])
        banned = card("Flash", color_identity=[], legalities={"commander": "legal"})
        entries = _make_deck(cmd, fill_cards=[banned], total=100)
        result = validate(entries)
        self.assertTrue(any("Flash" in e for e in result.errors))


class PartnerTests(unittest.TestCase):
    def test_invalid_partner_pair_gives_error(self):
        # Two random legends don't have Partner
        c1 = legendary_creature("Legend A", color_identity=["W"])
        c2 = legendary_creature("Legend B", color_identity=["U"])
        result = validate([c1, c2])
        self.assertFalse(result.valid)
        self.assertTrue(any("Partner" in e or "partner" in e.lower() for e in result.errors))

    def test_two_partner_commanders_valid(self):
        c1 = card("Partner A", type_line="Legendary Creature — Human",
                  oracle_text="Partner", color_identity=["W"],
                  is_commander=True, legalities={"commander": "legal"})
        c1.keywords = ["Partner"]
        c2 = card("Partner B", type_line="Legendary Creature — Human",
                  oracle_text="Partner", color_identity=["U"],
                  is_commander=True, legalities={"commander": "legal"})
        c2.keywords = ["Partner"]
        result = validate([c1, c2])
        self.assertFalse(any("Partner" in e and "not a valid" in e for e in result.errors))


class GetCommanderColorIdentityTests(unittest.TestCase):
    def test_returns_combined_colors(self):
        c1 = legendary_creature("A", color_identity=["W", "U"])
        c2 = legendary_creature("B", color_identity=["B"])
        ci = get_commander_color_identity([c1, c2])
        self.assertIn("W", ci)
        self.assertIn("U", ci)
        self.assertIn("B", ci)

    def test_colorless_returns_empty(self):
        cmd = card("Karn", type_line="Legendary Artifact Creature",
                   color_identity=[], is_commander=True)
        ci = get_commander_color_identity([cmd])
        self.assertEqual(ci, [])

    def test_non_commander_cards_ignored(self):
        cmd = legendary_creature("A", color_identity=["W"])
        non_cmd = card("Blue Card", color_identity=["U"])
        ci = get_commander_color_identity([cmd, non_cmd])
        self.assertNotIn("U", ci)


class ValidationResultModelTests(unittest.TestCase):
    def test_valid_by_default(self):
        r = ValidationResult()
        self.assertTrue(r.valid)
        self.assertEqual(r.errors, [])

    def test_add_error_makes_invalid(self):
        r = ValidationResult()
        r.add_error("Something broke")
        self.assertFalse(r.valid)
        self.assertIn("Something broke", r.errors)

    def test_add_warning_stays_valid(self):
        r = ValidationResult()
        r.add_warning("Minor issue")
        self.assertTrue(r.valid)
        self.assertIn("Minor issue", r.warnings)

    def test_to_dict_has_expected_keys(self):
        r = ValidationResult()
        d = r.to_dict()
        self.assertIn("valid", d)
        self.assertIn("errors", d)
        self.assertIn("warnings", d)


if __name__ == "__main__":
    unittest.main()
