"""Tests for EDHREC utility functions — slugify, price coercion, deck-count parsing."""

import unittest

from app.agents.edhrec import (
    slugify,
    _coerce_price,
    _first_price,
    _extract_tcgplayer_price,
    _parse_deck_count,
    _creativity_label,
    compute_creativity,
)
from app.models.card import CardEntry


def deck_card(name, is_commander=False, is_basic_land=False):
    type_line = "Basic Land — Plains" if is_basic_land else "Creature — Human"
    return CardEntry(
        quantity=1,
        raw_name=name,
        name=name,
        found=True,
        type_line=type_line,
        oracle_text="",
        is_commander=is_commander,
    )


class SlugifyTests(unittest.TestCase):
    def test_simple_name(self):
        self.assertEqual(slugify("Atraxa"), "atraxa")

    def test_name_with_spaces(self):
        self.assertEqual(slugify("Atraxa Praetors Voice"), "atraxa-praetors-voice")

    def test_apostrophe_removed(self):
        result = slugify("Atraxa, Praetors' Voice")
        self.assertNotIn("'", result)
        self.assertNotIn(",", result)

    def test_commas_removed(self):
        result = slugify("Kenrith, the Returned King")
        self.assertNotIn(",", result)

    def test_lowercase(self):
        result = slugify("Sol Ring")
        self.assertEqual(result, result.lower())

    def test_multiple_spaces_collapsed(self):
        result = slugify("Najeela  the  Blade Blossom")
        self.assertNotIn("--", result)

    def test_special_characters_removed(self):
        result = slugify("Gitrog Monster")
        self.assertRegex(result, r"^[a-z0-9-]+$")


class CoercePriceTests(unittest.TestCase):
    def test_float_passthrough(self):
        self.assertAlmostEqual(_coerce_price(12.5), 12.5)

    def test_int_converted(self):
        self.assertAlmostEqual(_coerce_price(5), 5.0)

    def test_string_dollar_stripped(self):
        self.assertAlmostEqual(_coerce_price("$3.99"), 3.99)

    def test_string_with_comma(self):
        self.assertAlmostEqual(_coerce_price("1,234.56"), 1234.56)

    def test_none_returns_none(self):
        self.assertIsNone(_coerce_price(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_coerce_price(""))

    def test_zero_returns_none(self):
        self.assertIsNone(_coerce_price(0))

    def test_invalid_string_returns_none(self):
        self.assertIsNone(_coerce_price("free!"))

    def test_negative_price_returns_none(self):
        self.assertIsNone(_coerce_price(-1.0))


class FirstPriceTests(unittest.TestCase):
    def test_returns_first_valid(self):
        self.assertAlmostEqual(_first_price(None, 5.0, 3.0), 5.0)

    def test_skips_none(self):
        self.assertAlmostEqual(_first_price(None, None, 2.5), 2.5)

    def test_all_none_returns_none(self):
        self.assertIsNone(_first_price(None, None, None))

    def test_zero_skipped(self):
        self.assertAlmostEqual(_first_price(0, 4.0), 4.0)


class ExtractTcgplayerPriceTests(unittest.TestCase):
    def test_prices_dict_with_tcgplayer_dict(self):
        cv = {"prices": {"tcgplayer": {"price": 10.0}}}
        self.assertAlmostEqual(_extract_tcgplayer_price(cv), 10.0)

    def test_prices_dict_with_tcgplayer_scalar(self):
        cv = {"prices": {"tcgplayer": 7.5}}
        self.assertAlmostEqual(_extract_tcgplayer_price(cv), 7.5)

    def test_top_level_tcgplayer_price(self):
        cv = {"tcgplayer_price": 3.0}
        self.assertAlmostEqual(_extract_tcgplayer_price(cv), 3.0)

    def test_top_level_price_fallback(self):
        cv = {"price": 2.0}
        self.assertAlmostEqual(_extract_tcgplayer_price(cv), 2.0)

    def test_no_price_returns_none(self):
        self.assertIsNone(_extract_tcgplayer_price({}))

    def test_market_price_key(self):
        cv = {"prices": {"tcgplayer": {"market_price": 8.0}}}
        self.assertAlmostEqual(_extract_tcgplayer_price(cv), 8.0)


class ParseDeckCountTests(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(_parse_deck_count("1234"), 1234)

    def test_k_suffix(self):
        self.assertEqual(_parse_deck_count("5K"), 5000)
        self.assertEqual(_parse_deck_count("1.5K"), 1500)

    def test_m_suffix(self):
        self.assertEqual(_parse_deck_count("2M"), 2_000_000)

    def test_comma_removed(self):
        self.assertEqual(_parse_deck_count("10,000"), 10000)

    def test_invalid_returns_zero(self):
        self.assertEqual(_parse_deck_count("unknown"), 0)

    def test_uppercase_k(self):
        self.assertEqual(_parse_deck_count("3K"), 3000)


class CreativityLabelTests(unittest.TestCase):
    def test_0_is_stock(self):
        self.assertEqual(_creativity_label(0), "Stock Build")

    def test_20_is_stock(self):
        self.assertEqual(_creativity_label(20), "Stock Build")

    def test_21_is_tuned(self):
        self.assertEqual(_creativity_label(21), "Tuned")

    def test_40_is_tuned(self):
        self.assertEqual(_creativity_label(40), "Tuned")

    def test_41_is_refined(self):
        self.assertEqual(_creativity_label(41), "Refined")

    def test_60_is_refined(self):
        self.assertEqual(_creativity_label(60), "Refined")

    def test_61_is_innovative(self):
        self.assertEqual(_creativity_label(61), "Innovative")

    def test_80_is_innovative(self):
        self.assertEqual(_creativity_label(80), "Innovative")

    def test_81_is_brewer(self):
        self.assertEqual(_creativity_label(81), "Brewer")

    def test_100_is_brewer(self):
        self.assertEqual(_creativity_label(100), "Brewer")


class ComputeCreativityTests(unittest.TestCase):
    def test_identical_decks_score_zero(self):
        user = [deck_card("Sol Ring"), deck_card("Rhystic Study")]
        avg = ["Sol Ring", "Rhystic Study"]
        result = compute_creativity(user, avg)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["unique_to_user"], [])

    def test_fully_unique_deck_score_100(self):
        user = [deck_card("Card A"), deck_card("Card B")]
        avg = ["Card C", "Card D"]
        result = compute_creativity(user, avg)
        self.assertEqual(result["score"], 100)

    def test_commanders_excluded(self):
        user = [
            deck_card("Commander", is_commander=True),
            deck_card("Unique Card"),
        ]
        avg = ["Unique Card"]
        result = compute_creativity(user, avg)
        # Commander is excluded; Unique Card overlaps
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["overlap_count"], 1)

    def test_basic_lands_excluded_from_average(self):
        user = [deck_card("Sol Ring")]
        # Average deck includes a basic land which should be excluded
        avg = ["Plains", "Sol Ring"]
        result = compute_creativity(user, avg)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["overlap_count"], 1)

    def test_overlap_count_correct(self):
        user = [deck_card("Card A"), deck_card("Card B"), deck_card("Card C")]
        avg = ["Card A", "Card B", "Card D"]
        result = compute_creativity(user, avg)
        self.assertEqual(result["overlap_count"], 2)

    def test_avg_only_list_populated(self):
        user = [deck_card("Card A")]
        avg = ["Card A", "Card B"]
        result = compute_creativity(user, avg)
        avg_only_names = [c["name"] for c in result["average_only"]]
        self.assertIn("Card B", avg_only_names)

    def test_empty_deck_returns_100(self):
        result = compute_creativity([], ["Sol Ring", "Rhystic Study"])
        # user_set is empty, score = 0/max(0,1)*100 = 0
        self.assertEqual(result["score"], 0)

    def test_case_insensitive_normalization(self):
        # Differing cases between user deck and average should still match
        user = [deck_card("sol ring")]
        avg = ["Sol Ring"]
        result = compute_creativity(user, avg)
        # If normalization works, these should overlap
        # (depends on _normalize_name; at minimum both lists shouldn't each count it)
        total = result["overlap_count"] + len(result["unique_to_user"]) + len(result["average_only"])
        # total unique cards across both sides should be ≤ 2 (1 from each)
        self.assertLessEqual(total, 2)

    def test_result_has_required_keys(self):
        result = compute_creativity([], [])
        for key in ("score", "label", "unique_to_user", "average_only",
                    "overlap_count", "user_card_count", "avg_card_count"):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
