import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.ai.lesson_draft_dto import (
    DraftGenerationError,
    DraftRequestValidationError,
    DraftResponseParseError,
    DraftResponseValidationError,
    LessonDraftGenerationRequest,
    build_generation_request,
)
from app.ai.lesson_draft_generator import generate_lesson_draft
from app.ai.lesson_draft_prompt import LESSON_DRAFT_PROMPT_VERSION


def _words(n: int) -> list[dict]:
    return [
        {"source": f"word{i}", "translation": f"слово{i}", "example": f"Example {i}."}
        for i in range(n)
    ]


def _grammar(n: int) -> list[dict]:
    return [
        {"title": f"Rule {i}", "explanation": f"Explanation {i}.", "example": None}
        for i in range(n)
    ]


def _exercises(n: int) -> list[dict]:
    return [
        {
            "prompt": f"Choose the correct option {i}.",
            "options": ["A", "B", "C"],
            "correct_option_index": 0,
            "explanation": None,
        }
        for i in range(n)
    ]


def _payload(words_count: int, grammar_count: int, exercises_count: int) -> dict:
    return {
        "topic": "Present Simple: daily routines",
        "level": "A2",
        "words": _words(words_count),
        "grammar": _grammar(grammar_count),
        "exercises": _exercises(exercises_count),
    }


class FakeProvider:
    name = "polza"

    def __init__(self, content=None, *, raise_exc=None, available=True, model="fake-model"):
        self._content = content
        self._raise_exc = raise_exc
        self.available = available
        self.model = model
        self.calls = []

    async def generate_lesson_draft(self, *, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._content


def _request(**overrides) -> LessonDraftGenerationRequest:
    params = dict(lesson_id=1, topic="Travel vocabulary", level="A2", words_count=5, grammar_count=1, exercises_count=3)
    params.update(overrides)
    return build_generation_request(**params)


class BuildGenerationRequestTests(unittest.TestCase):
    def test_valid_request(self) -> None:
        request = _request()
        self.assertEqual(request.level, "A2")

    def test_rejects_too_short_topic(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(topic="ab")

    def test_rejects_too_long_topic(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(topic="a" * 201)

    def test_rejects_invalid_level(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(level="C2")

    def test_rejects_invalid_words_count(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(words_count=7)

    def test_rejects_forged_bool_count(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(words_count=True)

    def test_rejects_zero_total(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(words_count=0, grammar_count=0, exercises_count=0)

    def test_rejects_total_over_limit(self) -> None:
        with self.assertRaises(DraftRequestValidationError):
            _request(words_count=20, grammar_count=3, exercises_count=10)


class GenerateLessonDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_generates_valid_draft_from_plain_json(self) -> None:
        content = json.dumps(_payload(5, 1, 3))
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content)):
            draft = await generate_lesson_draft(_request())
        self.assertEqual(draft.topic, "Present Simple: daily routines")
        self.assertEqual(len(draft.words), 5)
        self.assertEqual(len(draft.grammar), 1)
        self.assertEqual(len(draft.exercises), 3)
        self.assertEqual(draft.words[0].source, "word0")
        self.assertEqual(draft.exercises[0].correct_option_index, 0)

    async def test_generates_valid_draft_from_fenced_json(self) -> None:
        content = "```json\n" + json.dumps(_payload(5, 1, 3)) + "\n```"
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content)):
            draft = await generate_lesson_draft(_request())
        self.assertEqual(len(draft.grammar), 1)

    async def test_generates_valid_draft_from_bare_fence(self) -> None:
        content = "```\n" + json.dumps(_payload(5, 1, 3)) + "\n```"
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content)):
            draft = await generate_lesson_draft(_request())
        self.assertEqual(len(draft.exercises), 3)

    async def test_provider_unavailable_raises_generation_error(self) -> None:
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(None, available=False)):
            with self.assertRaises(DraftGenerationError):
                await generate_lesson_draft(_request())

    async def test_provider_returns_none_raises_generation_error(self) -> None:
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(None)):
            with self.assertRaises(DraftGenerationError):
                await generate_lesson_draft(_request())

    async def test_provider_raises_network_error(self) -> None:
        with patch(
            "app.ai.lesson_draft_generator.PolzaAIProvider",
            return_value=FakeProvider(None, raise_exc=TimeoutError("boom")),
        ):
            with self.assertRaises(DraftGenerationError):
                await generate_lesson_draft(_request())

    async def test_malformed_json_raises_parse_error(self) -> None:
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider("not json{")):
            with self.assertRaises(DraftResponseParseError):
                await generate_lesson_draft(_request())

    async def test_non_object_json_raises_parse_error(self) -> None:
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider("[1, 2, 3]")):
            with self.assertRaises(DraftResponseParseError):
                await generate_lesson_draft(_request())

    async def test_word_count_mismatch_raises_validation_error(self) -> None:
        payload = _payload(4, 1, 3)
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_unknown_top_level_key_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["extra"] = "nope"
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_duplicate_word_source_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["words"][1]["source"] = payload["words"][0]["source"].upper()
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_word_source_equal_translation_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["words"][0]["translation"] = payload["words"][0]["source"]
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_duplicate_grammar_title_is_rejected(self) -> None:
        payload = _payload(5, 2, 3)
        payload["grammar"][1]["title"] = payload["grammar"][0]["title"].upper()
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request(grammar_count=2))

    async def test_exercise_with_too_few_options_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["exercises"][0]["options"] = ["only one"]
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_exercise_with_too_many_options_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["exercises"][0]["options"] = ["A", "B", "C", "D", "E", "F", "G"]
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_exercise_with_duplicate_options_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["exercises"][0]["options"] = ["Same", "same", "Different"]
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_exercise_with_out_of_range_correct_index_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["exercises"][0]["correct_option_index"] = 5
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_exercise_with_bool_correct_index_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["exercises"][0]["correct_option_index"] = True
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_exercise_with_negative_correct_index_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["exercises"][0]["correct_option_index"] = -1
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_word_with_unknown_key_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["words"][0]["lesson_id"] = 42
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_empty_word_source_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["words"][0]["source"] = "   "
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_invalid_level_in_response_is_rejected(self) -> None:
        payload = _payload(5, 1, 3)
        payload["level"] = "Z9"
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_generation_creates_metadata(self) -> None:
        content = json.dumps(_payload(5, 1, 3))
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content, model="deepseek/deepseek-v4-flash")):
            draft = await generate_lesson_draft(_request())
        self.assertIsInstance(draft.metadata.generation_id, uuid.UUID)
        self.assertEqual(draft.metadata.provider, "polza")
        self.assertEqual(draft.metadata.model, "deepseek/deepseek-v4-flash")
        self.assertEqual(draft.metadata.prompt_version, LESSON_DRAFT_PROMPT_VERSION)

    async def test_generated_at_is_timezone_aware_utc(self) -> None:
        content = json.dumps(_payload(5, 1, 3))
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content)):
            draft = await generate_lesson_draft(_request())
        generated_at = draft.metadata.generated_at
        self.assertIsInstance(generated_at, datetime)
        self.assertIsNotNone(generated_at.tzinfo)
        self.assertEqual(generated_at.utcoffset(), timezone.utc.utcoffset(None))

    async def test_generated_at_uses_injected_clock(self) -> None:
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        content = json.dumps(_payload(5, 1, 3))
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content)):
            draft = await generate_lesson_draft(_request(), clock=lambda: fixed)
        self.assertEqual(draft.metadata.generated_at, fixed)

    async def test_two_successful_generations_create_different_generation_ids(self) -> None:
        content = json.dumps(_payload(5, 1, 3))
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(content)):
            first = await generate_lesson_draft(_request())
            second = await generate_lesson_draft(_request())
        self.assertNotEqual(first.metadata.generation_id, second.metadata.generation_id)

    async def test_failed_generation_does_not_reach_metadata_creation(self) -> None:
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider("not json{")):
            with self.assertRaises(DraftResponseParseError):
                await generate_lesson_draft(_request())

    async def test_metadata_keys_are_not_accepted_from_ai_response(self) -> None:
        payload = _payload(5, 1, 3)
        payload["generation_id"] = str(uuid.uuid4())
        payload["provider"] = "polza"
        payload["model"] = "deepseek/deepseek-v4-flash"
        payload["prompt_version"] = 1
        payload["generated_at"] = "2026-01-01T00:00:00+00:00"
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            with self.assertRaises(DraftResponseValidationError):
                await generate_lesson_draft(_request())

    async def test_metadata_not_required_in_ai_json_shape(self) -> None:
        # The AI contract has exactly topic/level/words/grammar/exercises — no metadata keys.
        payload = _payload(5, 1, 3)
        with patch("app.ai.lesson_draft_generator.PolzaAIProvider", return_value=FakeProvider(json.dumps(payload))):
            draft = await generate_lesson_draft(_request())
        self.assertTrue(hasattr(draft, "metadata"))


if __name__ == "__main__":
    unittest.main()
