"""Orchestration for AI lesson draft generation.

Responsible for validating the request, building the prompt, calling the
AI provider, extracting/parsing the JSON response, validating its
structure against strict business rules, and building the immutable
`GeneratedLessonDraft` DTO. Telegram handlers must not parse the model's
JSON themselves — they only call `generate_lesson_draft(request)`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.lesson_draft_dto import (
    ALLOWED_LEVELS,
    MAX_EXERCISE_EXPLANATION_LENGTH,
    MAX_EXERCISE_OPTION_LENGTH,
    MAX_EXERCISE_OPTIONS,
    MAX_EXERCISE_PROMPT_LENGTH,
    MAX_GRAMMAR_EXAMPLE_LENGTH,
    MAX_GRAMMAR_EXPLANATION_LENGTH,
    MAX_GRAMMAR_TITLE_LENGTH,
    MAX_WORD_EXAMPLE_LENGTH,
    MAX_WORD_SOURCE_LENGTH,
    MAX_WORD_TRANSLATION_LENGTH,
    MIN_EXERCISE_OPTIONS,
    DraftGenerationError,
    DraftResponseParseError,
    DraftResponseValidationError,
    GeneratedExerciseDraft,
    GeneratedGrammarDraft,
    GeneratedLessonDraft,
    GeneratedWordDraft,
    LessonDraftGenerationRequest,
    build_generation_request,
)
from app.ai.lesson_draft_prompt import SYSTEM_PROMPT, build_lesson_draft_user_prompt
from app.ai.polza_provider import PolzaAIProvider

logger = logging.getLogger(__name__)

_TOP_LEVEL_KEYS = {"topic", "level", "words", "grammar", "exercises"}
_WORD_KEYS = {"source", "translation", "example"}
_GRAMMAR_KEYS = {"title", "explanation", "example"}
_EXERCISE_KEYS = {"prompt", "options", "correct_option_index", "explanation"}


async def generate_lesson_draft(
    request: LessonDraftGenerationRequest,
) -> GeneratedLessonDraft:
    validated_request = build_generation_request(
        lesson_id=request.lesson_id,
        topic=request.topic,
        level=request.level,
        words_count=request.words_count,
        grammar_count=request.grammar_count,
        exercises_count=request.exercises_count,
    )

    provider = PolzaAIProvider()
    if not provider.available:
        logger.warning("Lesson draft generation requested but AI provider is unavailable")
        raise DraftGenerationError("AI provider is not configured")

    user_prompt = build_lesson_draft_user_prompt(validated_request)
    try:
        content = await provider.generate_lesson_draft(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
    except Exception as exc:  # defensive: provider should already catch, but never trust it fully
        logger.warning("Lesson draft AI call raised %s", type(exc).__name__)
        raise DraftGenerationError("AI provider call failed") from exc

    if content is None:
        logger.warning(
            "Lesson draft AI call returned no content (level=%s, words=%d, grammar=%d, exercises=%d)",
            validated_request.level,
            validated_request.words_count,
            validated_request.grammar_count,
            validated_request.exercises_count,
        )
        raise DraftGenerationError("AI provider returned no content")

    logger.info("Lesson draft AI response received (length=%d)", len(content))

    data = _parse_json_object(content)
    return _validate_and_build_draft(data, validated_request)


def _extract_json_object(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json_object(content: str) -> Any:
    text = _extract_json_object(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Lesson draft AI response was not valid JSON")
        raise DraftResponseParseError("AI response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise DraftResponseParseError("AI response JSON is not an object")
    return data


def _require_nonempty_str(value: Any, *, max_length: int, field: str) -> str:
    if not isinstance(value, str):
        raise DraftResponseValidationError(f"Field {field} must be a string")
    stripped = value.strip()
    if not stripped or len(stripped) > max_length:
        raise DraftResponseValidationError(f"Field {field} has invalid length")
    return stripped


def _optional_str(value: Any, *, max_length: int, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DraftResponseValidationError(f"Field {field} must be a string or null")
    stripped = value.strip()
    if len(stripped) > max_length:
        raise DraftResponseValidationError(f"Field {field} has invalid length")
    return stripped or None


def _validate_top_level(data: dict, request: LessonDraftGenerationRequest) -> None:
    unknown_keys = set(data.keys()) - _TOP_LEVEL_KEYS
    if unknown_keys:
        raise DraftResponseValidationError(f"Unknown top-level keys: {sorted(unknown_keys)}")
    for key in ("topic", "level"):
        if key not in data or not isinstance(data[key], str):
            raise DraftResponseValidationError(f"Missing or invalid field: {key}")
    if data["level"].strip().upper() not in ALLOWED_LEVELS:
        raise DraftResponseValidationError("Invalid level in AI response")
    for key in ("words", "grammar", "exercises"):
        if key not in data or not isinstance(data[key], list):
            raise DraftResponseValidationError(f"Missing or invalid field: {key}")

    if len(data["words"]) != request.words_count:
        raise DraftResponseValidationError("Word count mismatch")
    if len(data["grammar"]) != request.grammar_count:
        raise DraftResponseValidationError("Grammar count mismatch")
    if len(data["exercises"]) != request.exercises_count:
        raise DraftResponseValidationError("Exercise count mismatch")


def _validate_words(raw_words: list) -> tuple[GeneratedWordDraft, ...]:
    words: list[GeneratedWordDraft] = []
    seen_sources: set[str] = set()
    for item in raw_words:
        if not isinstance(item, dict):
            raise DraftResponseValidationError("Word entry must be an object")
        unknown_keys = set(item.keys()) - _WORD_KEYS
        if unknown_keys:
            raise DraftResponseValidationError(f"Unknown word keys: {sorted(unknown_keys)}")

        source = _require_nonempty_str(
            item.get("source"), max_length=MAX_WORD_SOURCE_LENGTH, field="source"
        )
        translation = _require_nonempty_str(
            item.get("translation"), max_length=MAX_WORD_TRANSLATION_LENGTH, field="translation"
        )
        example = _optional_str(
            item.get("example"), max_length=MAX_WORD_EXAMPLE_LENGTH, field="example"
        )

        if source.casefold() == translation.casefold():
            raise DraftResponseValidationError("Word source and translation must differ")
        key = source.casefold()
        if key in seen_sources:
            raise DraftResponseValidationError("Duplicate word source")
        seen_sources.add(key)

        words.append(GeneratedWordDraft(source=source, translation=translation, example=example))
    return tuple(words)


def _validate_grammar(raw_grammar: list) -> tuple[GeneratedGrammarDraft, ...]:
    items: list[GeneratedGrammarDraft] = []
    seen_titles: set[str] = set()
    for item in raw_grammar:
        if not isinstance(item, dict):
            raise DraftResponseValidationError("Grammar entry must be an object")
        unknown_keys = set(item.keys()) - _GRAMMAR_KEYS
        if unknown_keys:
            raise DraftResponseValidationError(f"Unknown grammar keys: {sorted(unknown_keys)}")

        title = _require_nonempty_str(
            item.get("title"), max_length=MAX_GRAMMAR_TITLE_LENGTH, field="title"
        )
        explanation = _require_nonempty_str(
            item.get("explanation"),
            max_length=MAX_GRAMMAR_EXPLANATION_LENGTH,
            field="explanation",
        )
        example = _optional_str(
            item.get("example"), max_length=MAX_GRAMMAR_EXAMPLE_LENGTH, field="example"
        )

        key = title.casefold()
        if key in seen_titles:
            raise DraftResponseValidationError("Duplicate grammar title")
        seen_titles.add(key)

        items.append(GeneratedGrammarDraft(title=title, explanation=explanation, example=example))
    return tuple(items)


def _validate_exercises(raw_exercises: list) -> tuple[GeneratedExerciseDraft, ...]:
    items: list[GeneratedExerciseDraft] = []
    for item in raw_exercises:
        if not isinstance(item, dict):
            raise DraftResponseValidationError("Exercise entry must be an object")
        unknown_keys = set(item.keys()) - _EXERCISE_KEYS
        if unknown_keys:
            raise DraftResponseValidationError(f"Unknown exercise keys: {sorted(unknown_keys)}")

        prompt = _require_nonempty_str(
            item.get("prompt"), max_length=MAX_EXERCISE_PROMPT_LENGTH, field="prompt"
        )

        raw_options = item.get("options")
        if not isinstance(raw_options, list):
            raise DraftResponseValidationError("Exercise options must be a list")
        if not (MIN_EXERCISE_OPTIONS <= len(raw_options) <= MAX_EXERCISE_OPTIONS):
            raise DraftResponseValidationError("Exercise options count out of range")

        options: list[str] = []
        seen_options: set[str] = set()
        for raw_option in raw_options:
            option = _require_nonempty_str(
                raw_option, max_length=MAX_EXERCISE_OPTION_LENGTH, field="option"
            )
            key = option.casefold()
            if key in seen_options:
                raise DraftResponseValidationError("Duplicate exercise option")
            seen_options.add(key)
            options.append(option)

        correct_index = item.get("correct_option_index")
        if isinstance(correct_index, bool) or not isinstance(correct_index, int):
            raise DraftResponseValidationError("correct_option_index must be an integer")
        if not (0 <= correct_index < len(options)):
            raise DraftResponseValidationError("correct_option_index out of range")

        explanation = _optional_str(
            item.get("explanation"),
            max_length=MAX_EXERCISE_EXPLANATION_LENGTH,
            field="explanation",
        )

        items.append(
            GeneratedExerciseDraft(
                prompt=prompt,
                options=tuple(options),
                correct_option_index=correct_index,
                explanation=explanation,
            )
        )
    return tuple(items)


def _validate_and_build_draft(
    data: dict, request: LessonDraftGenerationRequest
) -> GeneratedLessonDraft:
    _validate_top_level(data, request)

    topic = data["topic"].strip()
    level = data["level"].strip().upper()
    if not topic:
        raise DraftResponseValidationError("Topic must not be empty")

    words = _validate_words(data["words"])
    grammar = _validate_grammar(data["grammar"])
    exercises = _validate_exercises(data["exercises"])

    return GeneratedLessonDraft(
        topic=topic,
        level=level,
        words=words,
        grammar=grammar,
        exercises=exercises,
    )
