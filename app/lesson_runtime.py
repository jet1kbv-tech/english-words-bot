from __future__ import annotations

from enum import StrEnum

from app.lesson_repository import LessonRepository


class LessonSection(StrEnum):
    WORDS = "WORDS"
    GRAMMAR = "GRAMMAR"
    EXERCISES = "EXERCISES"
    HOMEWORK = "HOMEWORK"
    FINISHED = "FINISHED"


class LessonRuntimeService:
    """Determines the next lesson section independently of Telegram handlers."""

    def __init__(self, repository: LessonRepository) -> None:
        self.repository = repository

    def get_next_section(self, lesson_id: int, student_username: str) -> LessonSection | None:
        if self.repository.get_student_lesson(lesson_id, student_username) is None:
            return None
        return LessonSection.WORDS
