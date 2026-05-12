"""Tests for the synergy analyzer — role classification, clusters, warnings."""

import unittest
from unittest.mock import patch

from app.agents.synergy import (
    analyze,
    classify_role,
    SYNERGY_RULES,
    STAPLES_BY_COLOR,
)
from app.models.card import CardEntry


def card(name, type_line="Instant", oracle_text="", color_identity=None,
         is_commander=False, cmc=2.0, power=None, keywords=None, found=True):
    return CardEntry(
        quantity=1,
        raw_name=name,
        name=name,
        found=found,
        type_line=type_line,
        oracle_text=oracle_text,
        color_identity=color_identity or [],
        is_commander=is_commander,
        cmc=cmc,
        power=power,
        keywords=keywords or [],
    )


def land(name, color_identity=None):
    return card(name, type_line="Basic Land — Plains", cmc=0.0,
                color_identity=color_identity or ["W"])


def commander(name, color_identity=None, oracle_text=""):
    return card(name, type_line="Legendary Creature — Human",
                color_identity=color_identity or [], is_commander=True,
                oracle_text=oracle_text)


# Suppress otag lookups so tests don't need the otag index
@patch("app.agents.synergy.lookup_otags", return_value=[])
class ClassifyRoleTests(unittest.TestCase):
    def test_land_returns_lands(self, _mock):
        e = land("Plains")
        self.assertEqual(classify_role(e), "lands")

    def test_boardwipe_text_returns_boardwipes(self, _mock):
        e = card("Wrath of God", oracle_text="Destroy all creatures.")
        self.assertEqual(classify_role(e), "boardwipes")

    def test_exile_all_returns_boardwipes(self, _mock):
        e = card("Farewell", oracle_text="Exile all artifacts.")
        self.assertEqual(classify_role(e), "boardwipes")

    def test_removal_text_returns_removal(self, _mock):
        e = card("Murder", oracle_text="Destroy target creature.")
        self.assertEqual(classify_role(e), "removal")

    def test_tutor_text_returns_tutors(self, _mock):
        e = card("Demonic Tutor", oracle_text="Search your library for a card.")
        self.assertEqual(classify_role(e), "tutors")

    def test_draw_text_returns_draw(self, _mock):
        e = card("Rhystic Study", oracle_text="Whenever an opponent casts a spell, you may draw a card unless that player pays {1}.")
        self.assertEqual(classify_role(e), "draw")

    def test_ramp_text_returns_ramp(self, _mock):
        e = card("Cultivate", oracle_text="Search your library for up to two basic land cards, reveal them, put one into your hand and the other onto the battlefield tapped.")
        self.assertEqual(classify_role(e), "ramp")

    def test_high_power_creature_returns_threats(self, _mock):
        e = card("Big Creature", type_line="Creature — Beast", power="6")
        self.assertEqual(classify_role(e), "threats")

    def test_moderate_power_creature_is_synergy(self, _mock):
        e = card("Medium Creature", type_line="Creature — Human", power="3")
        self.assertEqual(classify_role(e), "synergy")

    def test_boardwipe_priority_over_removal(self, _mock):
        # "Destroy all" triggers boardwipe; "destroy target" is also in text
        e = card("Supreme Verdict",
                 oracle_text="Destroy all creatures. Destroy target permanent.")
        self.assertEqual(classify_role(e), "boardwipes")


@patch("app.agents.synergy.lookup_otags", return_value=[])
class SynergyClustersTests(unittest.TestCase):
    def _entries_with_draw(self, count=5):
        return [
            card(f"Draw Card {i}", oracle_text="draw a card") for i in range(count)
        ]

    def test_cluster_appears_when_3_plus_cards(self, _mock):
        entries = self._entries_with_draw(3)
        result = analyze(entries)
        cluster_names = [c["name"] for c in result["synergy_clusters"]]
        self.assertIn("Card Draw Engine", cluster_names)

    def test_cluster_absent_when_fewer_than_3(self, _mock):
        entries = self._entries_with_draw(2)
        result = analyze(entries)
        # Card Draw Engine needs 3+ hits; won't appear with 2
        cluster_names = [c["name"] for c in result["synergy_clusters"]]
        # It's possible Card Draw Engine still appears due to "whenever.*draw" overlap —
        # only assert that the count is less or it doesn't appear
        draw_cluster = next((c for c in result["synergy_clusters"] if c["name"] == "Card Draw Engine"), None)
        if draw_cluster:
            self.assertGreaterEqual(len(draw_cluster["cards"]), 3)

    def test_cluster_strength_high_for_8_plus(self, _mock):
        entries = self._entries_with_draw(9)
        result = analyze(entries)
        high = [c for c in result["synergy_clusters"] if c["strength"] == "high"]
        self.assertTrue(len(high) > 0)

    def test_token_generation_cluster(self, _mock):
        entries = [
            card(f"Token Maker {i}", oracle_text="Create a 1/1 creature token.")
            for i in range(4)
        ]
        result = analyze(entries)
        cluster_names = [c["name"] for c in result["synergy_clusters"]]
        self.assertIn("Token Generation", cluster_names)

    def test_graveyard_recursion_cluster(self, _mock):
        entries = [
            card(f"Reanimator {i}", oracle_text="Return target creature from your graveyard to the battlefield.")
            for i in range(3)
        ]
        result = analyze(entries)
        cluster_names = [c["name"] for c in result["synergy_clusters"]]
        self.assertIn("Graveyard Recursion", cluster_names)


@patch("app.agents.synergy.lookup_otags", return_value=[])
class ManaCurveTests(unittest.TestCase):
    def test_cmc_bucketed_correctly(self, _mock):
        entries = [
            card("One Drop", cmc=1.0),
            card("Two Drop", cmc=2.0),
            card("Three Drop", cmc=3.0),
        ]
        result = analyze(entries)
        self.assertEqual(result["mana_curve"]["1"], 1)
        self.assertEqual(result["mana_curve"]["2"], 1)
        self.assertEqual(result["mana_curve"]["3"], 1)

    def test_high_cmc_bucketed_at_7(self, _mock):
        entries = [card("Eldrazi", cmc=15.0)]
        result = analyze(entries)
        self.assertIn("7+", result["mana_curve"])
        self.assertEqual(result["mana_curve"]["7+"], 1)

    def test_lands_excluded_from_curve(self, _mock):
        entries = [land("Plains")]
        result = analyze(entries)
        self.assertEqual(result["mana_curve"].get("0", 0), 0)

    def test_avg_cmc_computed(self, _mock):
        entries = [
            card("Card A", cmc=2.0),
            card("Card B", cmc=4.0),
        ]
        result = analyze(entries)
        self.assertAlmostEqual(result["avg_cmc"], 3.0)


@patch("app.agents.synergy.lookup_otags", return_value=[])
class TypeBreakdownTests(unittest.TestCase):
    def test_creature_counted(self, _mock):
        entries = [card("A Creature", type_line="Creature — Human")]
        result = analyze(entries)
        self.assertEqual(result["type_breakdown"]["Creatures"], 1)

    def test_instant_counted(self, _mock):
        entries = [card("Murder", type_line="Instant")]
        result = analyze(entries)
        self.assertEqual(result["type_breakdown"]["Instants"], 1)

    def test_land_counted(self, _mock):
        entries = [land("Plains")]
        result = analyze(entries)
        self.assertEqual(result["type_breakdown"]["Lands"], 1)

    def test_artifact_creature_counts_as_creature_not_artifact(self, _mock):
        entries = [card("Myr Battlesphere", type_line="Artifact Creature — Myr")]
        result = analyze(entries)
        self.assertEqual(result["type_breakdown"]["Creatures"], 1)
        self.assertEqual(result["type_breakdown"]["Artifacts"], 0)


@patch("app.agents.synergy.lookup_otags", return_value=[])
class MissingStaplesTests(unittest.TestCase):
    def test_sol_ring_missing_if_not_in_deck(self, _mock):
        cmd = commander("Atraxa", color_identity=["W", "U", "B", "G"])
        entries = [cmd, card("Some Card")]
        result = analyze(entries)
        self.assertIn("Sol Ring", result["missing_staples"])

    def test_sol_ring_not_missing_if_in_deck(self, _mock):
        cmd = commander("Atraxa", color_identity=["W", "U", "B", "G"])
        sol = card("Sol Ring")
        entries = [cmd, sol]
        result = analyze(entries)
        self.assertNotIn("Sol Ring", result["missing_staples"])

    def test_color_specific_staples_included(self, _mock):
        cmd = commander("Mono Blue Legend", color_identity=["U"])
        entries = [cmd, card("Some Card")]
        result = analyze(entries)
        # Should suggest blue staples like Counterspell if not in deck
        self.assertIn("Counterspell", result["missing_staples"])

    def test_max_12_missing_staples(self, _mock):
        cmd = commander("5c Legend", color_identity=["W", "U", "B", "R", "G"])
        entries = [cmd]
        result = analyze(entries)
        self.assertLessEqual(len(result["missing_staples"]), 12)


@patch("app.agents.synergy.lookup_otags", return_value=[])
class WarningTests(unittest.TestCase):
    def test_low_ramp_warning(self, _mock):
        entries = [card("Random Card")]  # 0 ramp cards
        result = analyze(entries)
        self.assertTrue(any("ramp" in w.lower() for w in result["warnings"]))

    def test_low_land_warning(self, _mock):
        entries = [card("Random Card")]  # 0 lands
        result = analyze(entries)
        self.assertTrue(any("land" in w.lower() for w in result["warnings"]))

    def test_low_draw_warning(self, _mock):
        entries = [card("Random Card")]  # 0 draw
        result = analyze(entries)
        self.assertTrue(any("draw" in w.lower() for w in result["warnings"]))

    def test_high_land_count_warning(self, _mock):
        entries = [land(f"Plains {i}") for i in range(42)]
        result = analyze(entries)
        self.assertTrue(any("High land count" in w for w in result["warnings"]))

    def test_no_warnings_for_balanced_deck(self, _mock):
        # 10+ ramp, 10+ draw, 10+ removal/wipes, 36-40 lands
        ramp = [card(f"Ramp {i}", oracle_text="add {G}") for i in range(10)]
        draw = [card(f"Draw {i}", oracle_text="draw a card") for i in range(10)]
        removal = [card(f"Removal {i}", oracle_text="destroy target creature.") for i in range(5)]
        boardwipes = [card(f"Wipe {i}", oracle_text="Destroy all creatures.") for i in range(5)]
        lands = [land(f"Land {i}") for i in range(37)]
        entries = ramp + draw + removal + boardwipes + lands
        result = analyze(entries)
        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
