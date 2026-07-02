from __future__ import annotations

from app.tutorial.tutorial_models import Tutorial, TutorialStep

STUDENT_ONBOARDING = "student_onboarding"
TEACHER_ONBOARDING = "teacher_onboarding"

_TUTORIALS = {
    STUDENT_ONBOARDING: Tutorial(
        key=STUDENT_ONBOARDING,
        role="STUDENT",
        title="🚀 Начало работы",
        steps=[
            TutorialStep("👋 Добро пожаловать!", "Этот бот поможет вам изучать английский вместе с преподавателем.", feature_key="student_welcome"),
            TutorialStep("📚 Мои уроки", "📚 Все уроки находятся в разделе «Мои уроки».", feature_key="student_lessons"),
            TutorialStep("Состав урока", "Каждый урок может состоять из:\n\n• Words\n• Grammar\n• Exercises\n• Homework", feature_key="lesson_sections"),
            TutorialStep("🤖 AI", "🤖 AI помогает разбирать ошибки и готовить материалы, но финальное решение всегда остаётся за преподавателем.", feature_key="ai_helper"),
            TutorialStep("Готово!", "Готово!\n\nМожно приступать 🚀", feature_key="student_ready"),
        ],
    ),
    TEACHER_ONBOARDING: Tutorial(
        key=TEACHER_ONBOARDING,
        role="TEACHER",
        title="🚀 Начало работы",
        steps=[
            TutorialStep("Добро пожаловать!", "Вы создаёте уроки, назначаете их ученикам, а AI помогает подготовить материалы.", feature_key="teacher_welcome"),
            TutorialStep("Типичный сценарий", "Типичный сценарий:\n\n1. Создать Lesson\n2. Добавить слова\n3. Проверить AI-предложения\n4. Назначить ученику", feature_key="teacher_workflow"),
            TutorialStep("AI", "AI — помощник, а не замена преподавателя.\n\nВсе материалы можно проверить и отредактировать вручную.", feature_key="teacher_ai"),
            TutorialStep("Готово!", "Готово!\n\nМожно создавать первый урок 🚀", feature_key="teacher_ready"),
        ],
    ),
}


def get_tutorial(key: str) -> Tutorial | None:
    return _TUTORIALS.get(key)


def tutorial_for_role(role: str) -> Tutorial | None:
    normalized = role.upper()
    for tutorial in _TUTORIALS.values():
        if tutorial.role == normalized:
            return tutorial
    return None
