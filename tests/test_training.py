import unittest

from app.ai import AnswerCheckResult, AIService, build_ai_service, simple_check_answer
from app.handlers.training import build_game_session_words, card_weight


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


class AIServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_without_provider_falls_back_to_simple_check(self) -> None:
        service = AIService()

        result = await service.check_answer(prompt="hello", expected_answer="привет", user_answer="Привет")

        self.assertTrue(result.is_correct)
        self.assertFalse(result.used_ai)

    def test_build_ai_service_without_key_disables_provider(self) -> None:
        service = build_ai_service(provider_name="polza", api_key="", base_url="https://polza.ai/api/v1", model="model")

        self.assertIsNone(service.provider)


class AnswerCheckResultTests(unittest.TestCase):
    def test_ai_result_can_mark_provider_usage(self) -> None:
        result = AnswerCheckResult(is_correct=True, feedback="ок", used_ai=True)

        self.assertTrue(result.is_correct)
        self.assertEqual(result.feedback, "ок")
        self.assertTrue(result.used_ai)


if __name__ == "__main__":
    unittest.main()
