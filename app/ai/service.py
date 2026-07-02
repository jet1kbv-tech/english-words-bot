from __future__ import annotations

import json
import os

from app.ai.polza_provider import AICheckResult, PolzaAIProvider


async def check_text_answer(*, english: str, translation: str, direction: str, user_answer: str) -> AICheckResult | None:
    if os.getenv("AI_PROVIDER", "polza").strip().lower() != "polza":
        return None
    provider = PolzaAIProvider()
    return await provider.check_answer(
        english=english,
        translation=translation,
        direction=direction,
        user_answer=user_answer,
    )


async def generate_word_translations(words: list[str]) -> list[dict[str, str]] | None:
    if os.getenv("AI_PROVIDER", "polza").strip().lower() != "polza" or not words:
        return None
    provider = PolzaAIProvider()
    content = await provider.generate_word_translations(words=words)
    if not content:
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and isinstance(data.get("translations"), list):
        data = data["translations"]
    if not isinstance(data, list) or len(data) != len(words):
        return None
    expected = {word.casefold(): word for word in words}
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        english = item.get("english")
        translation = item.get("translation")
        if not isinstance(english, str) or not isinstance(translation, str):
            return None
        key = english.strip().casefold()
        if key not in expected or key in seen or not translation.strip():
            return None
        seen.add(key)
        result.append({"english": expected[key], "translation": translation.strip()[:500]})
    return result if seen == set(expected) else None
