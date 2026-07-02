from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AICheckResult:
    is_correct: bool
    feedback: str


class PolzaAIProvider:
    def __init__(self) -> None:
        self.api_key = os.getenv("POLZA_API_KEY", "").strip()
        self.base_url = os.getenv("POLZA_BASE_URL", "https://polza.ai/api/v1").strip()
        self.model = os.getenv("AI_MODEL", "deepseek/deepseek-v4-flash").strip()
        self._client = None
        if self.api_key and importlib.util.find_spec("openai") is not None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    @property
    def available(self) -> bool:
        return bool(self._client and self.model)

    async def check_answer(self, *, english: str, translation: str, direction: str, user_answer: str) -> AICheckResult | None:
        if not self.available:
            return None

        payload = {
            "english": english,
            "translation": translation,
            "direction": direction,
            "user_answer": user_answer,
        }
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты проверяешь ответ в упражнении на перевод. "
                            "Верни только JSON с полями is_correct (boolean) и feedback "
                            "(коротко по-русски). Учитывай опечатки, синонимы и смысл."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except Exception:
            return None

        content = response.choices[0].message.content if response.choices else None
        if not content:
            return None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None

        is_correct = data.get("is_correct")
        if not isinstance(is_correct, bool):
            return None
        feedback = data.get("feedback", "")
        if not isinstance(feedback, str):
            feedback = ""
        return AICheckResult(is_correct=is_correct, feedback=feedback.strip()[:200])

    async def generate_word_translations(self, *, words: list[str]) -> str | None:
        if not self.available or not words:
            return None

        from app.ai.word_translation_prompt import SYSTEM_PROMPT, build_word_translation_user_prompt

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_word_translation_user_prompt(words)},
                ],
                temperature=0,
            )
        except Exception:
            return None
        return response.choices[0].message.content if response.choices else None
