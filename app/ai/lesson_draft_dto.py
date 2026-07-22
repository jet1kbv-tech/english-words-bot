"""Typed DTOs and validation for the AI lesson draft generator.

These structures are independent of Telegram and the database: the
generator produces a `GeneratedLessonDraft` that lives only in memory
(`context.user_data`) until a future PR adds a save/merge step.
"""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1")

MIN_TOPIC_LENGTH = 3
MAX_TOPIC_LENGTH = 200

ALLOWED_WORDS_COUNTS: tuple[int, ...] = (0, 5, 10, 15, 20)
ALLOWED_GRAMMAR_COUNTS: tuple[int, ...] = (0, 1, 2, 3)
ALLOWED_EXERCISES_COUNTS: tuple[int, ...] = (0, 3, 5, 7, 10)

DEFAULT_WORDS_COUNT = 10
DEFAULT_GRAMMAR_COUNT = 2
DEFAULT_EXERCISES_COUNT = 5

MAX_TOTAL_ITEMS = 30

MAX_WORD_SOURCE_LENGTH = 100
MAX_WORD_TRANSLATION_LENGTH = 200
MAX_WORD_EXAMPLE_LENGTH = 300

MAX_GRAMMAR_TITLE_LENGTH = 150
MAX_GRAMMAR_EXPLANATION_LENGTH = 1500
MAX_GRAMMAR_EXAMPLE_LENGTH = 500

MAX_EXERCISE_PROMPT_LENGTH = 500
MIN_EXERCISE_OPTIONS = 2
MAX_EXERCISE_OPTIONS = 6
MAX_EXERCISE_OPTION_LENGTH = 200
MAX_EXERCISE_EXPLANATION_LENGTH = 800


class DraftRequestValidationError(ValueError):
    """Raised when the requested generation parameters are invalid."""


class DraftGenerationError(Exception):
    """Raised when the AI provider call itself fails (network/timeout/API)."""


class DraftResponseParseError(Exception):
    """Raised when the AI response is not valid JSON."""


class DraftResponseValidationError(Exception):
    """Raised when the parsed JSON does not satisfy the draft schema."""


@dataclass(frozen=True)
class LessonDraftGenerationRequest:
    lesson_id: int
    topic: str
    level: str
    words_count: int
    grammar_count: int
    exercises_count: int


@dataclass(frozen=True)
class GeneratedWordDraft:
    source: str
    translation: str
    example: str | None = None


@dataclass(frozen=True)
class GeneratedGrammarDraft:
    title: str
    explanation: str
    example: str | None = None


@dataclass(frozen=True)
class GeneratedExerciseDraft:
    prompt: str
    options: tuple[str, ...]
    correct_option_index: int
    explanation: str | None = None


@dataclass(frozen=True)
class GeneratedLessonDraft:
    topic: str
    level: str
    words: tuple[GeneratedWordDraft, ...]
    grammar: tuple[GeneratedGrammarDraft, ...]
    exercises: tuple[GeneratedExerciseDraft, ...]


def validate_topic(raw_topic: str) -> str:
    topic = raw_topic.strip()
    if len(topic) < MIN_TOPIC_LENGTH or len(topic) > MAX_TOPIC_LENGTH:
        raise DraftRequestValidationError(
            f"Тема должна быть от {MIN_TOPIC_LENGTH} до {MAX_TOPIC_LENGTH} символов."
        )
    return topic


def validate_level(raw_level: str) -> str:
    level = raw_level.strip().upper()
    if level not in ALLOWED_LEVELS:
        raise DraftRequestValidationError("Недопустимый уровень.")
    return level


def _validate_count(value: int, allowed: tuple[int, ...], label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DraftRequestValidationError(f"Недопустимое значение параметра «{label}».")
    if value not in allowed:
        raise DraftRequestValidationError(f"Недопустимое значение параметра «{label}».")
    return value


def build_generation_request(
    *,
    lesson_id: int,
    topic: str,
    level: str,
    words_count: int,
    grammar_count: int,
    exercises_count: int,
) -> LessonDraftGenerationRequest:
    validated_topic = validate_topic(topic)
    validated_level = validate_level(level)
    validated_words_count = _validate_count(words_count, ALLOWED_WORDS_COUNTS, "Слова")
    validated_grammar_count = _validate_count(grammar_count, ALLOWED_GRAMMAR_COUNTS, "Грамматика")
    validated_exercises_count = _validate_count(
        exercises_count, ALLOWED_EXERCISES_COUNTS, "Упражнения"
    )

    total = validated_words_count + validated_grammar_count + validated_exercises_count
    if total <= 0:
        raise DraftRequestValidationError(
            "Нужно выбрать хотя бы один элемент для генерации (слова, грамматику или упражнения)."
        )
    if total > MAX_TOTAL_ITEMS:
        raise DraftRequestValidationError(
            f"Слишком большой объём генерации: максимум {MAX_TOTAL_ITEMS} элементов суммарно."
        )

    return LessonDraftGenerationRequest(
        lesson_id=lesson_id,
        topic=validated_topic,
        level=validated_level,
        words_count=validated_words_count,
        grammar_count=validated_grammar_count,
        exercises_count=validated_exercises_count,
    )
