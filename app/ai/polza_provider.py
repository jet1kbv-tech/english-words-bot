from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.ai.service import AnswerCheckResult

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolzaProvider:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 10.0

    async def check_answer(self, *, prompt: str, expected_answer: str, user_answer: str) -> AnswerCheckResult | None:
        if not self.api_key:
            return None
        return await asyncio.to_thread(
            self._check_answer_sync,
            prompt=prompt,
            expected_answer=expected_answer,
            user_answer=user_answer,
        )

    def _check_answer_sync(self, *, prompt: str, expected_answer: str, user_answer: str) -> AnswerCheckResult | None:
        system_prompt = (
            "You check answers in an English/Russian vocabulary Telegram bot. "
            "Accept typos, inflections, synonyms, and word order differences when the meaning matches. "
            "Return only compact JSON with keys is_correct (boolean) and feedback (short Russian string)."
        )
        user_prompt = (
            f"Prompt shown to learner: {prompt}\n"
            f"Expected answer: {expected_answer}\n"
            f"Learner answer: {user_answer}\n"
            "Is the learner answer correct?"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            verdict = json.loads(content)
            return AnswerCheckResult(
                is_correct=bool(verdict.get("is_correct")),
                feedback=str(verdict.get("feedback") or "").strip() or None,
                used_ai=True,
            )
        except (OSError, urllib.error.URLError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.warning("Polza AI answer check is unavailable: %s", exc)
            return None
