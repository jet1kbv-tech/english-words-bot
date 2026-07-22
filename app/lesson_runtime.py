from __future__ import annotations

from enum import StrEnum

from app.lesson_repository import LessonRepository


class LessonSection(StrEnum):
    WORDS = "WORDS"
    GRAMMAR = "GRAMMAR"
    EXERCISES = "EXERCISES"
    HOMEWORK = "HOMEWORK"
    FINISHED = "FINISHED"


SECTION_ORDER: tuple[LessonSection, ...] = (
    LessonSection.WORDS,
    LessonSection.GRAMMAR,
    LessonSection.EXERCISES,
    LessonSection.HOMEWORK,
    LessonSection.FINISHED,
)

_CONTENT_COUNT_KEYS = {
    LessonSection.GRAMMAR: "grammar_count",
    LessonSection.EXERCISES: "exercises_count",
    LessonSection.HOMEWORK: "homework_count",
}


class LessonRuntimeService:
    """Determines the next lesson section independently of Telegram handlers."""

    def __init__(self, repository: LessonRepository) -> None:
        self.repository = repository

    def get_next_section(self, lesson_id: int, student_username: str) -> LessonSection | None:
        student_lesson = self.repository.get_student_lesson(lesson_id, student_username)
        if student_lesson is None:
            return None
        stored = student_lesson["current_section"] if "current_section" in student_lesson.keys() else None
        try:
            return LessonSection(stored) if stored else LessonSection.WORDS
        except ValueError:
            return LessonSection.WORDS

    def _has_content(self, summary, section: LessonSection) -> bool:
        key = _CONTENT_COUNT_KEYS.get(section)
        if key is None:
            return True
        return int(summary[key] or 0) > 0 if key in summary.keys() else False

    def advance_section(self, lesson_id: int, student_username: str) -> LessonSection | None:
        """Move past the current section, skipping any empty ones, and persist the result."""
        current = self.get_next_section(lesson_id, student_username)
        summary = self.repository.get_student_lesson(lesson_id, student_username)
        if current is None or summary is None:
            return None
        index = SECTION_ORDER.index(current)
        next_section = LessonSection.FINISHED
        for candidate in SECTION_ORDER[index + 1 :]:
            if self._has_content(summary, candidate):
                next_section = candidate
                break
        self.repository.set_student_lesson_section(lesson_id, student_username, next_section.value)
        return next_section
