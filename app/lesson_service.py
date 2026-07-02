from __future__ import annotations

import sqlite3

from app.lesson_repository import LessonRepository


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
