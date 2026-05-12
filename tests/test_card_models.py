"""Tests for card.py data models — properties, validation result, bracket assessment."""

import unittest

from app.models.card import CardEntry, ValidationResult, SynergyCluster, BracketAssessment


def entry(**kwargs):
    defaults = dict(
        quantity=1,
        raw_name="Test Card",
        name="Test Card",
        found=True,
        type_line="",
        oracle_text="",
    )
    defaults.update(kwargs)
    return CardEntry(**defaults)


class CardEntryPropertyTests(unittest.TestCase):
    def test_is_creature(self):
        self.assertTrue(entry(type_line="Creature — Human").is_creature)
        self.assertFalse(entry(type_line="Instant").is_creature)
        self.assertTrue(entry(type_line="Legendary Creature — Dragon").is_creature)
        self.assertTrue(entry(type_line="Artifact Creature — Construct").is_creature)

    def test_is_land(self):
        self.assertTrue(entry(type_line="Basic Land — Forest").is_land)
        self.assertTrue(entry(type_line="Land").is_land)
        self.assertFalse(entry(type_line="Creature — Human").is_land)

    def test_is_artifact(self):
        self.assertTrue(entry(type_line="Artifact").is_artifact)
        # Artifact Creature still is_artifact
        self.assertTrue(entry(type_line="Artifact Creature — Construct").is_artifact)
        self.assertFalse(entry(type_line="Instant").is_artifact)

    def test_is_enchantment(self):
        self.assertTrue(entry(type_line="Enchantment").is_enchantment)
        self.assertFalse(entry(type_line="Creature — Human").is_enchantment)

    def test_is_instant(self):
        self.assertTrue(entry(type_line="Instant").is_instant)
        self.assertFalse(entry(type_line="Sorcery").is_instant)

    def test_is_sorcery(self):
        self.assertTrue(entry(type_line="Sorcery").is_sorcery)
        self.assertFalse(entry(type_line="Instant").is_sorcery)

    def test_is_planeswalker(self):
        self.assertTrue(entry(type_line="Legendary Planeswalker — Jace").is_planeswalker)
        self.assertFalse(entry(type_line="Creature — Human").is_planeswalker)

    def test_is_legendary(self):
        self.assertTrue(entry(type_line="Legendary Creature — Human").is_legendary)
        self.assertFalse(entry(type_line="Creature — Human").is_legendary)

    def test_is_basic_land(self):
        self.assertTrue(entry(type_line="Basic Land — Forest").is_basic_land)
        self.assertTrue(entry(type_line="Basic Snow Land — Forest").is_basic_land)
        self.assertFalse(entry(type_line="Land").is_basic_land)
        self.assertFalse(entry(type_line="Creature — Human").is_basic_land)

    def test_can_be_commander_requires_legal_legality(self):
        legal_cmd = entry(
            type_line="Legendary Creature — Human",
            legalities={"commander": "legal"},
        )
        self.assertTrue(legal_cmd.can_be_commander)

    def test_cannot_be_commander_if_not_legal(self):
        illegal = entry(
            type_line="Legendary Creature — Human",
            legalities={"commander": "not_legal"},
        )
        self.assertFalse(illegal.can_be_commander)

    def test_cannot_be_commander_if_no_legalities(self):
        no_leg = entry(type_line="Legendary Creature — Human", legalities={})
        self.assertFalse(no_leg.can_be_commander)

    def test_to_dict_contains_all_fields(self):
        e = entry(type_line="Creature — Human", cmc=3.0)
        d = e.to_dict()
        self.assertIn("quantity", d)
        self.assertIn("name", d)
        self.assertIn("type_line", d)
        self.assertIn("oracle_text", d)
        self.assertIn("cmc", d)
        self.assertIn("found", d)
        self.assertIn("game_changer", d)

    def test_default_found_is_false(self):
        e = CardEntry(quantity=1, raw_name="Test")
        self.assertFalse(e.found)

    def test_color_identity_defaults_empty(self):
        e = CardEntry(quantity=1, raw_name="Test")
        self.assertEqual(e.color_identity, [])


class ValidationResultTests(unittest.TestCase):
    def test_new_result_is_valid(self):
        r = ValidationResult()
        self.assertTrue(r.valid)
        self.assertEqual(len(r.errors), 0)
        self.assertEqual(len(r.warnings), 0)

    def test_add_error_marks_invalid(self):
        r = ValidationResult()
        r.add_error("bad thing")
        self.assertFalse(r.valid)

    def test_multiple_errors_accumulate(self):
        r = ValidationResult()
        r.add_error("error one")
        r.add_error("error two")
        self.assertEqual(len(r.errors), 2)

    def test_add_warning_does_not_invalidate(self):
        r = ValidationResult()
        r.add_warning("minor concern")
        self.assertTrue(r.valid)
        self.assertEqual(len(r.warnings), 1)

    def test_to_dict(self):
        r = ValidationResult()
        r.add_error("oops")
        r.add_warning("heads up")
        d = r.to_dict()
        self.assertEqual(d["valid"], False)
        self.assertIn("oops", d["errors"])
        self.assertIn("heads up", d["warnings"])


class SynergyClusterTests(unittest.TestCase):
    def test_to_dict(self):
        c = SynergyCluster(
            name="Token Generation",
            description="Makes tokens",
            cards=["Rhys the Redeemed", "Anointed Procession"],
            strength="medium",
        )
        d = c.to_dict()
        self.assertEqual(d["name"], "Token Generation")
        self.assertEqual(d["strength"], "medium")
        self.assertIn("Rhys the Redeemed", d["cards"])

    def test_default_strength_medium(self):
        c = SynergyCluster(name="X", description="Y")
        self.assertEqual(c.strength, "medium")


class BracketAssessmentTests(unittest.TestCase):
    def test_to_dict_has_all_fields(self):
        b = BracketAssessment(
            bracket=3,
            label="Upgraded",
            reasoning=["Has a game changer"],
            game_changer_count=1,
            game_changer_cards=["Rhystic Study"],
            fast_mana_count=0,
            combo_potential="none",
        )
        d = b.to_dict()
        self.assertEqual(d["bracket"], 3)
        self.assertEqual(d["label"], "Upgraded")
        self.assertEqual(d["game_changer_count"], 1)
        self.assertIn("Rhystic Study", d["game_changer_cards"])

    def test_combo_potential_values(self):
        for val in ["none", "medium", "high"]:
            b = BracketAssessment(bracket=1, label="Exhibition", combo_potential=val)
            self.assertEqual(b.combo_potential, val)


if __name__ == "__main__":
    unittest.main()
