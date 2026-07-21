from __future__ import annotations

import sqlite3

from app.database import Database

LESSON_STATUS_DRAFT = "DRAFT"
LESSON_STATUS_PUBLISHED = "PUBLISHED"
LESSON_STATUS_ARCHIVED = "ARCHIVED"


class LessonRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_lesson(self, title: str, created_by_user_id: int | None = None) -> sqlite3.Row:
        return self.db.create_teacher_lesson(title, created_by_user_id)

    def list_lessons(self) -> list[sqlite3.Row]:
        return self.db.list_lessons()

    def get_lesson(self, lesson_id: int) -> sqlite3.Row | None:
        return self.db.get_lesson(lesson_id)

    def get_lesson_summary(self, lesson_id: int) -> sqlite3.Row | None:
        return self.db.get_lesson_summary(lesson_id)

    def list_lesson_words(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.db.list_lesson_words(lesson_id)

    def get_lesson_word(self, lesson_id: int, word_id: int) -> sqlite3.Row | None:
        return self.db.get_lesson_word(lesson_id, word_id)

    def list_lesson_training_words(self, lesson_id: int, user_id: int) -> list[sqlite3.Row]:
        return self.db.list_lesson_training_words(lesson_id, user_id)

    def list_homework_tasks(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.db.list_homework_tasks(lesson_id)

    def get_homework_task(self, lesson_id: int, task_id: int) -> sqlite3.Row | None:
        return self.db.get_homework_task(lesson_id, task_id)

    def delete_homework_task(self, lesson_id: int, task_id: int) -> bool:
        return self.db.delete_homework_task(lesson_id, task_id)

    def submit_homework_answer(
        self, task_id: int, user_id: int, answer: str, is_correct: bool | None = None, feedback: str | None = None
    ) -> sqlite3.Row:
        return self.db.submit_homework_answer(task_id, user_id, answer, is_correct, feedback)

    def list_latest_homework_answers(self, lesson_id: int, user_id: int) -> dict[int, sqlite3.Row]:
        return self.db.list_latest_homework_answers(lesson_id, user_id)

    def add_homework_task(
        self,
        lesson_id: int,
        task_type: str,
        prompt: str,
        expected_answer: str | None = None,
        metadata_json: str | None = None,
        order_index: int = 0,
    ) -> sqlite3.Row:
        return self.db.add_homework_task(lesson_id, task_type, prompt, expected_answer, metadata_json, order_index)

    def add_lesson_words(self, lesson_id: int, words: list[str], owner_user_id: int | None = None) -> list[sqlite3.Row]:
        return self.db.add_lesson_words(lesson_id, words, owner_user_id)

    def assign_lesson_to_student(self, lesson_id: int, student_username: str, assigned_by_user_id: int | None = None) -> sqlite3.Row:
        return self.db.assign_lesson_to_student(lesson_id, student_username, assigned_by_user_id)

    def unassign_lesson(self, lesson_id: int) -> None:
        self.db.unassign_lesson(lesson_id)

    def get_active_lesson_assignment(self, lesson_id: int) -> sqlite3.Row | None:
        return self.db.get_active_lesson_assignment(lesson_id)

    def list_lesson_assignment_history(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.db.list_lesson_assignment_history(lesson_id)

    def list_student_lessons(self, student_username: str) -> list[sqlite3.Row]:
        return self.db.list_student_lessons(student_username)

    def get_student_lesson(self, lesson_id: int, student_username: str) -> sqlite3.Row | None:
        return self.db.get_student_lesson(lesson_id, student_username)
