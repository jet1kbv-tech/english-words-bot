from __future__ import annotations

import json
import sqlite3

from app.lesson_repository import LessonRepository
from app.student_access_service import normalize_username

MAX_LESSON_WORDS_IMPORT = 300
MAX_LESSON_WORD_LENGTH = 200
MAX_HOMEWORK_PROMPT_LENGTH = 500
MAX_HOMEWORK_ANSWER_LENGTH = 500
MIN_QUIZ_OPTIONS = 2
MAX_QUIZ_OPTIONS = 6
MAX_QUIZ_OPTION_LENGTH = 200

HOMEWORK_TASK_TYPE_TRANSLATION = "translation"
HOMEWORK_TASK_TYPE_FREE = "free"
HOMEWORK_TASK_TYPE_QUIZ = "quiz"


class LessonWordImportError(ValueError):
    pass


class HomeworkTaskError(ValueError):
    pass


def _validated_prompt(prompt: str, *, empty_message: str) -> str:
    prompt = prompt.strip()
    if not prompt:
        raise HomeworkTaskError(empty_message)
    if len(prompt) > MAX_HOMEWORK_PROMPT_LENGTH:
        raise HomeworkTaskError(f"Слишком длинный текст: максимум {MAX_HOMEWORK_PROMPT_LENGTH} символов.")
    return prompt


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

    def assign_lesson_to_student(self, lesson_id: int, student_username: str, assigned_by_user_id: int | None = None) -> sqlite3.Row:
        normalized = normalize_username(student_username)
        if not normalized:
            raise ValueError("student username must not be empty")
        return self.repository.assign_lesson_to_student(lesson_id, normalized, assigned_by_user_id)

    def unassign_lesson(self, lesson_id: int) -> None:
        self.repository.unassign_lesson(lesson_id)

    def get_active_lesson_assignment(self, lesson_id: int) -> sqlite3.Row | None:
        return self.repository.get_active_lesson_assignment(lesson_id)

    def list_lesson_assignment_history(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.repository.list_lesson_assignment_history(lesson_id)

    def list_homework_tasks(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.repository.list_homework_tasks(lesson_id)

    def get_homework_task(self, lesson_id: int, task_id: int) -> sqlite3.Row | None:
        return self.repository.get_homework_task(lesson_id, task_id)

    def delete_homework_task(self, lesson_id: int, task_id: int) -> bool:
        return self.repository.delete_homework_task(lesson_id, task_id)

    def _next_homework_order_index(self, lesson_id: int) -> int:
        return len(self.repository.list_homework_tasks(lesson_id))

    def add_translation_task(self, lesson_id: int, prompt: str, expected_answer: str | None = None) -> sqlite3.Row:
        prompt = _validated_prompt(prompt, empty_message="Задание не может быть пустым.")
        expected = expected_answer.strip() if expected_answer else None
        if expected and len(expected) > MAX_HOMEWORK_ANSWER_LENGTH:
            raise HomeworkTaskError(f"Слишком длинный ответ: максимум {MAX_HOMEWORK_ANSWER_LENGTH} символов.")
        order_index = self._next_homework_order_index(lesson_id)
        return self.repository.add_homework_task(lesson_id, HOMEWORK_TASK_TYPE_TRANSLATION, prompt, expected or None, None, order_index)

    def add_free_task(self, lesson_id: int, prompt: str) -> sqlite3.Row:
        prompt = _validated_prompt(prompt, empty_message="Задание не может быть пустым.")
        order_index = self._next_homework_order_index(lesson_id)
        return self.repository.add_homework_task(lesson_id, HOMEWORK_TASK_TYPE_FREE, prompt, None, None, order_index)

    def add_quiz_task(self, lesson_id: int, prompt: str, options: list[str], correct_index: int) -> sqlite3.Row:
        prompt = _validated_prompt(prompt, empty_message="Вопрос не может быть пустым.")
        cleaned = [option.strip() for option in options if option.strip()]
        if len(cleaned) < MIN_QUIZ_OPTIONS:
            raise HomeworkTaskError(f"Нужно минимум {MIN_QUIZ_OPTIONS} варианта, каждый с новой строки.")
        if len(cleaned) > MAX_QUIZ_OPTIONS:
            raise HomeworkTaskError(f"Слишком много вариантов: максимум {MAX_QUIZ_OPTIONS}.")
        for option in cleaned:
            if len(option) > MAX_QUIZ_OPTION_LENGTH:
                raise HomeworkTaskError(f"Слишком длинный вариант: максимум {MAX_QUIZ_OPTION_LENGTH} символов.")
        if not (0 <= correct_index < len(cleaned)):
            raise HomeworkTaskError("Номер верного варианта вне диапазона.")
        metadata_json = json.dumps({"options": cleaned, "correct_index": correct_index}, ensure_ascii=False)
        order_index = self._next_homework_order_index(lesson_id)
        return self.repository.add_homework_task(lesson_id, HOMEWORK_TASK_TYPE_QUIZ, prompt, cleaned[correct_index], metadata_json, order_index)
