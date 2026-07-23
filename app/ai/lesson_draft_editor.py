"""Pure, Telegram- and SQLite-independent operations on the words section of
an in-memory `GeneratedLessonDraft`.

`GeneratedLessonDraft` and `GeneratedWordDraft` are frozen dataclasses, so
every function here returns a *new* draft instead of mutating anything —
callers are responsible for storing the result back into
`context.user_data`. On a validation failure nothing is touched: the input
draft is never partially modified.

Grammar and exercises are out of scope for this module.
"""

from __future__ import annotations

from dataclasses import replace

from app.ai.lesson_draft_dto import (
    MAX_WORD_EXAMPLE_LENGTH,
    MAX_WORD_SOURCE_LENGTH,
    MAX_WORD_TRANSLATION_LENGTH,
    GeneratedLessonDraft,
    GeneratedWordDraft,
)

WORD_FIELDS = ("source", "translation", "example")


class DraftEditError(ValueError):
    """Raised when a manual edit would produce invalid word data."""


class DraftEditIndexError(IndexError):
    """Raised when a word index does not exist in the draft."""


def _normalize_required(raw_value: str, *, max_length: int, field_label: str) -> str:
    value = raw_value.strip()
    if not value:
        raise DraftEditError(f"«{field_label}» не может быть пустым.")
    if len(value) > max_length:
        raise DraftEditError(f"«{field_label}»: максимум {max_length} символов.")
    return value


def _normalize_optional(raw_value: str | None, *, max_length: int, field_label: str) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise DraftEditError(f"«{field_label}»: максимум {max_length} символов.")
    return value


def _ensure_unique_source(words: tuple[GeneratedWordDraft, ...], candidate_source: str, *, skip_index: int | None = None) -> None:
    key = candidate_source.casefold()
    for position, word in enumerate(words):
        if position == skip_index:
            continue
        if word.source.casefold() == key:
            raise DraftEditError("Такое слово уже есть в черновике.")


def _validate_word_index(draft: GeneratedLessonDraft, index: int) -> None:
    if not (0 <= index < len(draft.words)):
        raise DraftEditIndexError("word index out of range")


def build_word(*, source: str, translation: str, example: str | None = None) -> GeneratedWordDraft:
    """Builds and validates a single word entry using the draft's field contract."""
    normalized_source = _normalize_required(source, max_length=MAX_WORD_SOURCE_LENGTH, field_label="Слово")
    normalized_translation = _normalize_required(translation, max_length=MAX_WORD_TRANSLATION_LENGTH, field_label="Перевод")
    normalized_example = _normalize_optional(example, max_length=MAX_WORD_EXAMPLE_LENGTH, field_label="Пример")
    if normalized_source.casefold() == normalized_translation.casefold():
        raise DraftEditError("Слово и перевод не должны совпадать.")
    return GeneratedWordDraft(source=normalized_source, translation=normalized_translation, example=normalized_example)


def add_word(draft: GeneratedLessonDraft, *, source: str, translation: str, example: str | None = None) -> GeneratedLessonDraft:
    """Returns a new draft with one more word appended."""
    new_word = build_word(source=source, translation=translation, example=example)
    _ensure_unique_source(draft.words, new_word.source)
    return replace(draft, words=draft.words + (new_word,))


def update_word_field(draft: GeneratedLessonDraft, index: int, field: str, raw_value: str) -> GeneratedLessonDraft:
    """Returns a new draft with one field of one word replaced.

    `field` must be one of `WORD_FIELDS` ("source", "translation", "example").
    """
    if field not in WORD_FIELDS:
        raise ValueError(f"unknown word field: {field}")
    _validate_word_index(draft, index)
    current = draft.words[index]

    if field == "source":
        new_source = _normalize_required(raw_value, max_length=MAX_WORD_SOURCE_LENGTH, field_label="Слово")
        _ensure_unique_source(draft.words, new_source, skip_index=index)
        updated = replace(current, source=new_source)
    elif field == "translation":
        updated = replace(current, translation=_normalize_required(raw_value, max_length=MAX_WORD_TRANSLATION_LENGTH, field_label="Перевод"))
    else:
        updated = replace(current, example=_normalize_optional(raw_value, max_length=MAX_WORD_EXAMPLE_LENGTH, field_label="Пример"))

    if updated.source.casefold() == updated.translation.casefold():
        raise DraftEditError("Слово и перевод не должны совпадать.")

    words = list(draft.words)
    words[index] = updated
    return replace(draft, words=tuple(words))


def delete_word(draft: GeneratedLessonDraft, index: int) -> GeneratedLessonDraft:
    """Returns a new draft with the word at `index` removed; later indexes shift down."""
    _validate_word_index(draft, index)
    words = list(draft.words)
    del words[index]
    return replace(draft, words=tuple(words))
