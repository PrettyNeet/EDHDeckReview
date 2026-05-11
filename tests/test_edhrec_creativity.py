import unittest

from app.agents.edhrec import compute_creativity
from app.models.card import CardEntry


def deck_card(name):
    return CardEntry(
        quantity=1,
        raw_name=name,
        name=name,
        found=True,
        type_line="Creature — Cat",
        oracle_text="",
        is_commander=False,
    )


class EdhrecCreativityTests(unittest.TestCase):
    def test_double_faced_full_name_matches_average_front_face(self):
        result = compute_creativity(
            [deck_card("Ajani, Nacatl Pariah // Ajani, Nacatl Avenger")],
            ["Ajani, Nacatl Pariah"],
        )

        self.assertEqual(result["overlap_count"], 1)
        self.assertEqual(result["unique_to_user"], [])
        self.assertEqual(result["average_only"], [])
        self.assertEqual(result["score"], 0)

    def test_double_faced_front_face_matches_average_full_name(self):
        result = compute_creativity(
            [deck_card("Ajani, Nacatl Pariah")],
            ["Ajani, Nacatl Pariah // Ajani, Nacatl Avenger"],
        )

        self.assertEqual(result["overlap_count"], 1)
        self.assertEqual(result["unique_to_user"], [])
        self.assertEqual(result["average_only"], [])


if __name__ == "__main__":
    unittest.main()
