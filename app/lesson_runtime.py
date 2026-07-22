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

_COMPLETED_COUNT_KEYS = {
    LessonSection.GRAMMAR: "grammar_completed_count",
    LessonSection.EXERCISES: "exercises_completed_count",
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

    def is_section_complete(self, summary, section: LessonSection) -> bool:
        """Whether `section` is done and the runtime may advance past it.

        GRAMMAR is complete once every grammar item has been confirmed by the
        student (`student_grammar_progress`); EXERCISES once every exercise has a
        saved first attempt (`lesson_exercise_answers`). An empty section (no
        items at all) is trivially complete. WORDS has no formal completion state
        (existing behavior, always passable) and HOMEWORK does not gate lesson
        completion - its own review flow can stay pending indefinitely, so it is
        always treated as complete for the purpose of advancing to FINISHED. See
        ARCHITECTURE.md 3.8 for this product decision.
        """
        count_key = _CONTENT_COUNT_KEYS.get(section)
        if count_key is None or section not in _COMPLETED_COUNT_KEYS:
            return True
        total = int(summary[count_key] or 0) if count_key in summary.keys() else 0
        if total == 0:
            return True
        completed_key = _COMPLETED_COUNT_KEYS[section]
        completed = int(summary[completed_key] or 0) if completed_key in summary.keys() else 0
        return completed >= total

    def advance_section(self, lesson_id: int, student_username: str) -> LessonSection | None:
        """Move past the current section, skipping any empty ones, and persist the
        result - but only if the current section is actually complete (see
        `is_section_complete`). If it isn't, this is a no-op that returns the
        unchanged current section: callers must not advance the stage themselves,
        this is the single place that enforces the gate."""
        current = self.get_next_section(lesson_id, student_username)
        summary = self.repository.get_student_lesson(lesson_id, student_username)
        if current is None or summary is None:
            return None
        if not self.is_section_complete(summary, current):
            return current
        index = SECTION_ORDER.index(current)
        next_section = LessonSection.FINISHED
        for candidate in SECTION_ORDER[index + 1 :]:
            if self._has_content(summary, candidate):
                next_section = candidate
                break
        self.repository.set_student_lesson_section(lesson_id, student_username, next_section.value)
        return next_section
