from __future__ import annotations

import json
import re
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
MAX_GRAMMAR_TITLE_LENGTH = 200
MAX_GRAMMAR_TEXT_LENGTH = 1500
MAX_EXERCISE_PROMPT_LENGTH = 500
MAX_EXERCISE_ANSWER_LENGTH = 200
MAX_EXERCISE_HINT_LENGTH = 500

HOMEWORK_TASK_TYPE_TRANSLATION = "translation"
HOMEWORK_TASK_TYPE_FREE = "free"
HOMEWORK_TASK_TYPE_QUIZ = "quiz"


class LessonWordImportError(ValueError):
    pass


class HomeworkTaskError(ValueError):
    pass


class GrammarItemError(ValueError):
    pass


class ExerciseItemError(ValueError):
    pass


def _validated_prompt(prompt: str, *, empty_message: str, max_length: int = MAX_HOMEWORK_PROMPT_LENGTH) -> str:
    prompt = prompt.strip()
    if not prompt:
        raise HomeworkTaskError(empty_message)
    if len(prompt) > max_length:
        raise HomeworkTaskError(f"Слишком длинный текст: максимум {max_length} символов.")
    return prompt


def _normalize_exercise_answer(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()


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

    def list_latest_homework_answers(self, lesson_id: int, user_id: int) -> dict[int, sqlite3.Row]:
        return self.repository.list_latest_homework_answers(lesson_id, user_id)

    def submit_homework_answer(
        self, lesson_id: int, task_id: int, user_id: int, answer: str, is_correct: bool | None = None, feedback: str | None = None
    ) -> sqlite3.Row:
        if self.repository.get_homework_task(lesson_id, task_id) is None:
            raise ValueError("homework task not found")
        answer = answer.strip()
        if not answer:
            raise HomeworkTaskError("Ответ не может быть пустым.")
        if len(answer) > MAX_HOMEWORK_ANSWER_LENGTH:
            raise HomeworkTaskError(f"Слишком длинный ответ: максимум {MAX_HOMEWORK_ANSWER_LENGTH} символов.")
        return self.repository.submit_homework_answer(task_id, user_id, answer, is_correct, feedback)

    def get_latest_homework_answer(self, task_id: int, user_id: int) -> sqlite3.Row | None:
        return self.repository.get_latest_homework_answer(task_id, user_id)

    def review_homework_answer(
        self, lesson_id: int, task_id: int, answer_id: int, is_correct: bool, feedback: str | None = None
    ) -> sqlite3.Row:
        if self.repository.get_homework_task(lesson_id, task_id) is None:
            raise ValueError("homework task not found")
        if self.repository.get_homework_answer(task_id, answer_id) is None:
            raise ValueError("homework answer not found")
        feedback = feedback.strip() if feedback else None
        if feedback and len(feedback) > MAX_HOMEWORK_ANSWER_LENGTH:
            raise HomeworkTaskError(f"Слишком длинный комментарий: максимум {MAX_HOMEWORK_ANSWER_LENGTH} символов.")
        return self.repository.review_homework_answer(answer_id, is_correct, feedback)

    def _next_grammar_position(self, lesson_id: int) -> int:
        return len(self.repository.list_grammar_items(lesson_id))

    def add_grammar_item(self, lesson_id: int, title: str, explanation: str, example: str | None = None) -> sqlite3.Row:
        title = title.strip()
        if not title:
            raise GrammarItemError("Заголовок не может быть пустым.")
        if len(title) > MAX_GRAMMAR_TITLE_LENGTH:
            raise GrammarItemError(f"Слишком длинный заголовок: максимум {MAX_GRAMMAR_TITLE_LENGTH} символов.")
        explanation = explanation.strip()
        if not explanation:
            raise GrammarItemError("Объяснение не может быть пустым.")
        if len(explanation) > MAX_GRAMMAR_TEXT_LENGTH:
            raise GrammarItemError(f"Слишком длинное объяснение: максимум {MAX_GRAMMAR_TEXT_LENGTH} символов.")
        example = example.strip() if example else None
        if example and len(example) > MAX_GRAMMAR_TEXT_LENGTH:
            raise GrammarItemError(f"Слишком длинный пример: максимум {MAX_GRAMMAR_TEXT_LENGTH} символов.")
        position = self._next_grammar_position(lesson_id)
        return self.repository.add_grammar_item(lesson_id, title, explanation, example or None, position)

    def list_grammar_items(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.repository.list_grammar_items(lesson_id)

    def get_grammar_item(self, lesson_id: int, item_id: int) -> sqlite3.Row | None:
        return self.repository.get_grammar_item(lesson_id, item_id)

    def delete_grammar_item(self, lesson_id: int, item_id: int) -> bool:
        return self.repository.delete_grammar_item(lesson_id, item_id)

    def _next_exercise_position(self, lesson_id: int) -> int:
        return len(self.repository.list_exercise_items(lesson_id))

    def add_exercise_item(self, lesson_id: int, prompt: str, expected_answer: str, hint: str | None = None) -> sqlite3.Row:
        prompt = _validated_prompt(prompt, empty_message="Задание не может быть пустым.", max_length=MAX_EXERCISE_PROMPT_LENGTH)
        expected_answer = expected_answer.strip()
        if not expected_answer:
            raise ExerciseItemError("Ответ не может быть пустым.")
        if len(expected_answer) > MAX_EXERCISE_ANSWER_LENGTH:
            raise ExerciseItemError(f"Слишком длинный ответ: максимум {MAX_EXERCISE_ANSWER_LENGTH} символов.")
        hint = hint.strip() if hint else None
        if hint and len(hint) > MAX_EXERCISE_HINT_LENGTH:
            raise ExerciseItemError(f"Слишком длинная подсказка: максимум {MAX_EXERCISE_HINT_LENGTH} символов.")
        position = self._next_exercise_position(lesson_id)
        return self.repository.add_exercise_item(lesson_id, prompt, expected_answer, hint or None, position)

    def list_exercise_items(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.repository.list_exercise_items(lesson_id)

    def get_exercise_item(self, lesson_id: int, item_id: int) -> sqlite3.Row | None:
        return self.repository.get_exercise_item(lesson_id, item_id)

    def delete_exercise_item(self, lesson_id: int, item_id: int) -> bool:
        return self.repository.delete_exercise_item(lesson_id, item_id)

    def submit_exercise_answer(self, lesson_id: int, exercise_id: int, user_id: int, answer: str) -> tuple[bool, sqlite3.Row]:
        item = self.repository.get_exercise_item(lesson_id, exercise_id)
        if item is None:
            raise ValueError("exercise item not found")
        answer = answer.strip()
        if not answer:
            raise ExerciseItemError("Ответ не может быть пустым.")
        if len(answer) > MAX_EXERCISE_ANSWER_LENGTH:
            raise ExerciseItemError(f"Слишком длинный ответ: максимум {MAX_EXERCISE_ANSWER_LENGTH} символов.")
        is_correct = _normalize_exercise_answer(answer) == _normalize_exercise_answer(str(item["expected_answer"]))
        row = self.repository.submit_exercise_answer(exercise_id, user_id, answer, is_correct)
        return is_correct, row

    def list_latest_exercise_answers(self, lesson_id: int, user_id: int) -> dict[int, sqlite3.Row]:
        return self.repository.list_latest_exercise_answers(lesson_id, user_id)
