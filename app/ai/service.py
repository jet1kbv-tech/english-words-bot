from __future__ import annotations

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
