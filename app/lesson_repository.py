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
