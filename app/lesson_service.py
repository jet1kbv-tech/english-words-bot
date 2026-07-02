from __future__ import annotations

import sqlite3

from app.lesson_repository import LessonRepository

MAX_LESSON_WORDS_IMPORT = 300
MAX_LESSON_WORD_LENGTH = 200


class LessonWordImportError(ValueError):
    pass


def normalize_lesson_words_import(text: str) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        word = line.strip()
        if not word:
            continue
        if len(word) > MAX_LESSON_WORD_LENGTH:
            raise LessonWordImportError(f"Слишком длинная строка: максимум {MAX_LESSON_WORD_LENGTH} символов.")
        if word in seen:
            continue
        seen.add(word)
        words.append(word)
    if not words:
        raise LessonWordImportError("Список слов пуст. Отправьте хотя бы одно слово.")
    if len(words) > MAX_LESSON_WORDS_IMPORT:
        raise LessonWordImportError(f"Слишком много слов: максимум {MAX_LESSON_WORDS_IMPORT} за один импорт.")
    return words


class LessonService:
    def __init__(self, repository: LessonRepository) -> None:
        self.repository = repository

    def create_lesson(self, title: str, created_by_user_id: int | None = None) -> sqlite3.Row:
        title = title.strip()
        if not title:
            raise ValueError("lesson title must not be empty")
        return self.repository.create_lesson(title, created_by_user_id)

    def list_lessons(self) -> list[sqlite3.Row]:
        return self.repository.list_lessons()

    def get_lesson(self, lesson_id: int) -> sqlite3.Row | None:
        return self.repository.get_lesson(lesson_id)

    def get_lesson_summary(self, lesson_id: int) -> sqlite3.Row | None:
        return self.repository.get_lesson_summary(lesson_id)

    def list_lesson_words(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.repository.list_lesson_words(lesson_id)

    def get_lesson_word(self, lesson_id: int, word_id: int) -> sqlite3.Row | None:
        return self.repository.get_lesson_word(lesson_id, word_id)

    def add_lesson_words(self, lesson_id: int, words: list[str], owner_user_id: int | None = None) -> list[sqlite3.Row]:
        if not words:
            raise ValueError("words must not be empty")
        return self.repository.add_lesson_words(lesson_id, words, owner_user_id)
