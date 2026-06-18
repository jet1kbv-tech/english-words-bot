import unittest

from app.handlers.training import card_weight


class TrainingWeightTests(unittest.TestCase):
    def test_card_weight_prioritizes_new_and_forgotten_words(self) -> None:
        cases = [
            (None, 5),
            (-1, 4),
            (0, 4),
            (1, 3),
            (2, 2),
            (3, 1),
            (10, 1),
        ]

        for score, expected_weight in cases:
            with self.subTest(score=score):
                self.assertEqual(card_weight(score), expected_weight)


if __name__ == "__main__":
    unittest.main()

from app.handlers.training import build_game_session_words


class GameSessionSelectionTests(unittest.TestCase):
    def test_game_session_limits_to_ten_and_includes_strong_review(self) -> None:
        words = []
        for index in range(8):
            words.append({"id": index, "progress_score": None})
        for index in range(8, 12):
            words.append({"id": index, "progress_score": 1})
        for index in range(12, 15):
            words.append({"id": index, "progress_score": 5})

        selected = build_game_session_words(words)

        self.assertEqual(len(selected), 10)
        self.assertTrue(any(word["progress_score"] == 5 for word in selected))
