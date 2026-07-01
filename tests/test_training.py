import unittest

from app.handlers.training import EN_TO_RU, RU_TO_EN, _is_text_answer_correct, _normalize_answer, build_game_session_words, build_mistake_session_words, card_weight


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


class MistakeSessionSelectionTests(unittest.TestCase):
    def test_mistake_session_prioritizes_low_score_and_forgotten_words(self) -> None:
        words = [
            {"id": 1, "progress_score": 5, "times_remembered": 5, "times_forgotten": 1},
            {"id": 2, "progress_score": 1, "times_remembered": 3, "times_forgotten": 0},
            {"id": 3, "progress_score": 4, "times_remembered": 1, "times_forgotten": 3},
        ]

        selected = build_mistake_session_words(words, limit=2)
        selected_ids = {word["id"] for word in selected}

        self.assertEqual(selected_ids, {2, 3})

    def test_mistake_session_fills_from_smart_review_when_needed(self) -> None:
        words = [
            {"id": 1, "progress_score": 0, "times_remembered": 0, "times_forgotten": 1},
            {"id": 2, "progress_score": None, "times_remembered": None, "times_forgotten": None},
            {"id": 3, "progress_score": 5, "times_remembered": 5, "times_forgotten": 0},
        ]

        selected = build_mistake_session_words(words, limit=3)

        self.assertEqual(len(selected), 3)
        self.assertIn(1, {word["id"] for word in selected})


class TextInputAnswerTests(unittest.TestCase):
    def test_normalize_answer_lower_strips_spaces_and_replaces_yo(self) -> None:
        self.assertEqual(_normalize_answer("  ЁЖ   большой  "), "еж большой")

    def test_ru_to_en_compares_with_english_word(self) -> None:
        word = {"english": "Receipt", "translation": "чек"}

        self.assertTrue(_is_text_answer_correct(word, RU_TO_EN, " receipt "))
        self.assertFalse(_is_text_answer_correct(word, RU_TO_EN, "bill"))

    def test_en_to_ru_accepts_translation_variants(self) -> None:
        word = {"english": "awkward", "translation": "неловкий / неудобный, нескладный; странный"}

        self.assertTrue(_is_text_answer_correct(word, EN_TO_RU, " Неудобный "))
        self.assertTrue(_is_text_answer_correct(word, EN_TO_RU, "странный"))
        self.assertFalse(_is_text_answer_correct(word, EN_TO_RU, "неловко"))
