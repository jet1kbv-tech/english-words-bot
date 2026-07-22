"""Contract tests for the AI lesson draft prompt builder.

These tests protect the *contract* (required semantic guarantees) without
pinning down exact prompt wording, so the prompt text can still be improved
freely. They never call the AI.
"""

import json
import unittest

from app.ai.lesson_draft_dto import LessonDraftGenerationRequest
from app.ai.lesson_draft_prompt import (
    LESSON_DRAFT_PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_lesson_draft_user_prompt,
)


class SystemPromptContractTests(unittest.TestCase):
    def test_requires_single_json_object_only(self) -> None:
        self.assertIn("один JSON", SYSTEM_PROMPT)
        self.assertIn("ничего кроме", SYSTEM_PROMPT)

    def test_forbids_markdown_and_code_fences(self) -> None:
        self.assertIn("markdown", SYSTEM_PROMPT)
        self.assertIn("блоков кода", SYSTEM_PROMPT)

    def test_forbids_text_before_or_after_json(self) -> None:
        self.assertIn("без пояснений до или после JSON", SYSTEM_PROMPT)

    def test_requires_russian_explanations_and_translations(self) -> None:
        self.assertIn("на русском", SYSTEM_PROMPT)

    def test_requires_english_learning_content(self) -> None:
        self.assertIn("на английском", SYSTEM_PROMPT)

    def test_requires_cefr_level_compliance(self) -> None:
        self.assertIn("CEFR", SYSTEM_PROMPT)

    def test_requires_single_choice_exercises_only(self) -> None:
        self.assertIn("одиночного выбора", SYSTEM_PROMPT)
        self.assertIn("single choice", SYSTEM_PROMPT)

    def test_requires_two_to_six_options(self) -> None:
        self.assertIn("от 2 до 6", SYSTEM_PROMPT)

    def test_requires_unique_options(self) -> None:
        self.assertIn("уникальных", SYSTEM_PROMPT)

    def test_requires_exactly_one_unambiguous_correct_option(self) -> None:
        self.assertIn("ровно один правильный", SYSTEM_PROMPT)
        self.assertIn("однозначным", SYSTEM_PROMPT)

    def test_requires_zero_based_correct_option_index(self) -> None:
        self.assertIn("correct_option_index", SYSTEM_PROMPT)
        self.assertIn("начиная с нуля", SYSTEM_PROMPT)
        self.assertIn("0-based", SYSTEM_PROMPT)

    def test_forbids_all_of_the_above_style_options(self) -> None:
        self.assertIn("все перечисленное", SYSTEM_PROMPT)

    def test_requires_exact_element_counts(self) -> None:
        self.assertIn("количество элементов", SYSTEM_PROMPT)
        self.assertIn("ровно столько", SYSTEM_PROMPT)

    def test_requires_exact_schema(self) -> None:
        self.assertIn("строго такой структуры", SYSTEM_PROMPT)

    def test_forbids_internal_or_telegram_fields(self) -> None:
        self.assertIn("lesson_id", SYSTEM_PROMPT)
        self.assertIn("user_id", SYSTEM_PROMPT)
        self.assertIn("status", SYSTEM_PROMPT)

    def test_restricts_unsuitable_content(self) -> None:
        self.assertIn("18+", SYSTEM_PROMPT)
        self.assertIn("насилие", SYSTEM_PROMPT)
        self.assertIn("политику", SYSTEM_PROMPT)

    def test_does_not_mention_generation_metadata(self) -> None:
        for forbidden in ("generation_id", "prompt_version", "provider", "generated_at"):
            self.assertNotIn(forbidden, SYSTEM_PROMPT)


class UserPromptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = LessonDraftGenerationRequest(
            lesson_id=42,
            topic="Travel vocabulary",
            level="B1",
            words_count=10,
            grammar_count=2,
            exercises_count=5,
        )
        self.prompt = build_lesson_draft_user_prompt(self.request)
        self.payload = json.loads(self.prompt)

    def test_contains_topic_level_and_counts(self) -> None:
        self.assertEqual(self.payload["topic"], "Travel vocabulary")
        self.assertEqual(self.payload["level"], "B1")
        self.assertEqual(self.payload["words_count"], 10)
        self.assertEqual(self.payload["grammar_count"], 2)
        self.assertEqual(self.payload["exercises_count"], 5)

    def test_contains_expected_json_shape(self) -> None:
        shape = self.payload["required_json_shape"]
        self.assertIn("topic", shape)
        self.assertIn("level", shape)
        self.assertIn("words", shape)
        self.assertIn("grammar", shape)
        self.assertIn("exercises", shape)
        self.assertIn("correct_option_index", shape["exercises"][0])

    def test_does_not_contain_lesson_id(self) -> None:
        # lesson_id is Telegram/DB routing data — it must never reach the AI.
        self.assertNotIn("lesson_id", self.prompt)
        self.assertNotIn("42", self.prompt)

    def test_does_not_contain_telegram_or_user_identifiers(self) -> None:
        for forbidden in ("user_id", "username", "telegram", "owner"):
            self.assertNotIn(forbidden, self.prompt.lower())

    def test_does_not_contain_secrets_or_provider_details(self) -> None:
        for forbidden in ("api_key", "polza.ai", "polza_api_key", "base_url"):
            self.assertNotIn(forbidden, self.prompt.lower())

    def test_does_not_contain_generation_metadata(self) -> None:
        for forbidden in ("generation_id", "prompt_version", "generated_at", "metadata"):
            self.assertNotIn(forbidden, self.prompt.lower())


class PromptVersionTests(unittest.TestCase):
    def test_prompt_version_is_pinned(self) -> None:
        self.assertEqual(LESSON_DRAFT_PROMPT_VERSION, 1)

    def test_prompt_version_is_an_int(self) -> None:
        self.assertIsInstance(LESSON_DRAFT_PROMPT_VERSION, int)


if __name__ == "__main__":
    unittest.main()
