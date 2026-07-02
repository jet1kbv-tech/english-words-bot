from __future__ import annotations

import json

SYSTEM_PROMPT = (
    "Ты переводишь английские слова и фразы на русский для урока английского. "
    "Верни строго JSON-массив объектов с полями english и translation. "
    "Никакого markdown. Никаких пояснений. Сохрани каждое english ровно как во входе."
)


def build_word_translation_user_prompt(words: list[str]) -> str:
    return json.dumps({"words": words}, ensure_ascii=False)
