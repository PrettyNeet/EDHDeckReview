import unittest

from app.agents.plan_analyzer import analyze_plan, detect_commander_role_matches
from app.agents.role_catalog import get_role_catalog, get_role_metadata
from app.models.card import CardEntry


def card(name, type_line, oracle_text="", is_commander=False, power=None):
    return CardEntry(
        quantity=1,
        raw_name=name,
        is_commander=is_commander,
        name=name,
        found=True,
        type_line=type_line,
        oracle_text=oracle_text,
        power=power,
        cmc=4,
    )


class RoleCatalogTests(unittest.TestCase):
    def test_catalog_loads_themes_and_typals(self):
        catalog = get_role_catalog()
        self.assertGreaterEqual(len(catalog["themes"]), 200)
        self.assertGreaterEqual(len(catalog["typals"]), 100)
        self.assertEqual(catalog["themes"][0]["name"], "Tokens")
        self.assertEqual(catalog["typals"][0]["name"], "Dragons")

    def test_metadata_resolves_aliases(self):
        self.assertEqual(get_role_metadata("Artifact Matters")["name"], "Artifacts")
        self.assertEqual(get_role_metadata("Dragon")["name"], "Dragons")

    def test_typal_detection_uses_commander_and_deck_evidence(self):
        commander = card(
            "Miirym, Sentinel Wyrm",
            "Legendary Creature — Dragon Spirit",
            "Whenever another nontoken Dragon enters the battlefield under your control, create a token that is a copy of it.",
            is_commander=True,
            power="6",
        )
        deck = [commander] + [
            card(f"Dragon {index}", "Creature — Dragon", "Flying")
            for index in range(12)
        ]

        matches = detect_commander_role_matches(commander, deck)
        self.assertEqual(matches[0]["name"], "Dragons")
        self.assertEqual(matches[0]["kind"], "typal")
        self.assertIn("12 Dragons", "; ".join(matches[0]["evidence"]))

    def test_user_override_keeps_detected_matches_separate(self):
        commander = card(
            "Token Commander",
            "Legendary Creature — Human",
            "Whenever you cast a spell, create a 1/1 creature token.",
            is_commander=True,
            power="2",
        )
        plan = analyze_plan([commander], commander_roles_override=["Artifacts"])

        self.assertEqual(plan["commander_roles"], ["Artifacts"])
        self.assertEqual(plan["commander_roles_source"], "user")
        self.assertIn("Tokens", plan["detected_commander_roles"])
        self.assertEqual(plan["commander_role_details"][0]["name"], "Artifacts")


if __name__ == "__main__":
    unittest.main()
