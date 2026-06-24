import unittest

from app.ai import AnswerCheckResult, simple_check_answer
from app.handlers.training import build_game_session_words, card_weight
from app.keyboards import ADD_WORD, BULK_ADD_WORDS, GAME_SESSION, MAIN_MENU, MY_CARDS, MY_WORDS, PROGRESS, WORD_EXCHANGE, main_menu_keyboard


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


class MainMenuKeyboardTests(unittest.TestCase):
    def test_main_menu_contains_all_expected_actions(self) -> None:
        keyboard = main_menu_keyboard().keyboard
        button_texts = [button.text for row in keyboard for button in row]

        self.assertEqual(
            button_texts,
            [
                MAIN_MENU,
                ADD_WORD,
                BULK_ADD_WORDS,
                MY_WORDS,
                WORD_EXCHANGE,
                MY_CARDS,
                GAME_SESSION,
                PROGRESS,
            ],
        )


class SimpleAnswerCheckTests(unittest.TestCase):
    def test_simple_check_accepts_exact_case_insensitive_answer(self) -> None:
        result = simple_check_answer("Hello", " hello ")

        self.assertTrue(result.is_correct)
        self.assertFalse(result.used_ai)

    def test_simple_check_accepts_comma_separated_variant(self) -> None:
        result = simple_check_answer("привет, здравствуй", "Здравствуй")

        self.assertTrue(result.is_correct)

    def test_simple_check_rejects_different_answer(self) -> None:
        result = simple_check_answer("hello", "bye")

        self.assertFalse(result.is_correct)


class AnswerCheckResultTests(unittest.TestCase):
    def test_ai_result_can_mark_provider_usage(self) -> None:
        result = AnswerCheckResult(is_correct=True, feedback="ок", used_ai=True)

        self.assertTrue(result.is_correct)
        self.assertEqual(result.feedback, "ок")
        self.assertTrue(result.used_ai)


if __name__ == "__main__":
    unittest.main()
