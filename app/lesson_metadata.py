from __future__ import annotations

import re
from typing import Any

_LESSON_TITLE_PATTERN = re.compile(r"^(?:lesson\s+)?(?P<number>\d+)\s*[—-]\s*(?P<topic>.+)$", re.IGNORECASE)


def parse_lesson_title(title: str) -> tuple[int | None, str | None]:
    """Extract lightweight lesson metadata from a teacher-entered title."""
    original = title.strip()
    if not original:
        return None, None
    match = _LESSON_TITLE_PATTERN.match(original)
    if match:
        return int(match.group("number")), match.group("topic").strip() or None
    return None, original


def _get_value(lesson: Any, key: str) -> Any:
    if hasattr(lesson, "keys") and key in lesson.keys():
        return lesson[key]
    if isinstance(lesson, dict):
        return lesson.get(key)
    return getattr(lesson, key, None)


def lesson_display_name(lesson: Any) -> str:
    lesson_number = _get_value(lesson, "lesson_number")
    topic = _get_value(lesson, "topic")
    title = _get_value(lesson, "title")
    if lesson_number is not None and topic:
        return f"Lesson {lesson_number} — {topic}"
    if topic:
        return str(topic)
    return str(title or "Lesson")
