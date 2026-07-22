"""Prompt building for the AI lesson draft generator."""

from __future__ import annotations

import json

from app.ai.lesson_draft_dto import LessonDraftGenerationRequest

SYSTEM_PROMPT = (
    "Ты — автор структурированного учебного контента для урока английского языка. "
    "Объяснения и переводы пиши на русском языке. Изучаемый язык, примеры и упражнения — "
    "на английском. Строго соблюдай уровень CEFR, который тебе передан. "
    "Не используй темы 18+, насилие, наркотики, политику и другие темы, неуместные для учебного контента. "
    "Верни строго один JSON-объект и ничего кроме него: без markdown, без блоков кода, "
    "без пояснений до или после JSON. "
    "Строго соблюдай запрошенное количество элементов в каждом списке — ровно столько, сколько указано. "
    "Все упражнения — только одиночного выбора (single choice): у каждого от 2 до 6 уникальных "
    "непустых вариантов ответа и ровно один правильный. Поле correct_option_index — это "
    "индекс правильного варианта, начиная с нуля (0-based). Правильный вариант должен быть "
    "однозначным: не используй формулировки вида «все перечисленное» и не допускай, чтобы "
    "несколько вариантов были одновременно фактически верны. "
    "Объяснение грамматики должно быть коротким и соответствовать уровню. "
    "Слова не должны повторяться (без учёта регистра), поле source и поле translation "
    "не должны быть пустыми. Примеры должны быть короткими. "
    "Верни JSON строго такой структуры: "
    '{"topic": string, "level": string, '
    '"words": [{"source": string, "translation": string, "example": string|null}], '
    '"grammar": [{"title": string, "explanation": string, "example": string|null}], '
    '"exercises": [{"prompt": string, "options": [string, ...], '
    '"correct_option_index": number, "explanation": string|null}]}'
)


def build_lesson_draft_user_prompt(request: LessonDraftGenerationRequest) -> str:
    payload = {
        "topic": request.topic,
        "level": request.level,
        "words_count": request.words_count,
        "grammar_count": request.grammar_count,
        "exercises_count": request.exercises_count,
        "required_json_shape": {
            "topic": "string",
            "level": "string",
            "words": [{"source": "string", "translation": "string", "example": "string|null"}],
            "grammar": [{"title": "string", "explanation": "string", "example": "string|null"}],
            "exercises": [
                {
                    "prompt": "string",
                    "options": ["string", "..."],
                    "correct_option_index": "number",
                    "explanation": "string|null",
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False)
