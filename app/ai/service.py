from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AnswerCheckResult:
    is_correct: bool
    feedback: str | None = None
    used_ai: bool = False


class AnswerCheckProvider(Protocol):
    async def check_answer(self, *, prompt: str, expected_answer: str, user_answer: str) -> AnswerCheckResult | None:
        """Return an AI verdict, or None when the provider is unavailable."""


def normalize_answer(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip(" .,!?:;\n\t\r")


def simple_check_answer(expected_answer: str, user_answer: str) -> AnswerCheckResult:
    expected = normalize_answer(expected_answer)
    actual = normalize_answer(user_answer)
    if not expected or not actual:
        return AnswerCheckResult(is_correct=False)

    variants = {part.strip() for part in re.split(r"[,;/]", expected) if part.strip()}
    return AnswerCheckResult(is_correct=actual == expected or actual in variants)


@dataclass(frozen=True)
class AIService:
    provider: AnswerCheckProvider | None = None

    async def check_answer(self, *, prompt: str, expected_answer: str, user_answer: str) -> AnswerCheckResult:
        if self.provider is not None:
            result = await self.provider.check_answer(prompt=prompt, expected_answer=expected_answer, user_answer=user_answer)
            if result is not None:
                return result
        return simple_check_answer(expected_answer, user_answer)


def build_ai_service(*, provider_name: str, api_key: str, base_url: str, model: str) -> AIService:
    if provider_name.casefold() != "polza" or not api_key:
        return AIService()

    from app.ai.polza_provider import PolzaProvider

    return AIService(provider=PolzaProvider(api_key=api_key, base_url=base_url, model=model))
