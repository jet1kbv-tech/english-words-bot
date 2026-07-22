"""Direct tests for PolzaAIProvider covering the per-call temperature contract.

These bypass the real openai.AsyncOpenAI client entirely (no network calls)
by injecting a fake `_client` after construction.
"""

import unittest
from types import SimpleNamespace

from app.ai.polza_provider import PolzaAIProvider


class _FakeChatCompletions:
    def __init__(self, content: str = "{}"):
        self.calls: list[dict] = []
        self._content = content

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _FakeOpenAIClient:
    def __init__(self, content: str = "{}"):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions(content))


def _fake_provider(content: str = "{}") -> tuple[PolzaAIProvider, _FakeOpenAIClient]:
    provider = PolzaAIProvider()
    fake_client = _FakeOpenAIClient(content)
    provider._client = fake_client
    provider.model = "test-model"
    return provider, fake_client


class PolzaProviderTemperatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_lesson_draft_uses_temperature_0_4(self) -> None:
        provider, fake_client = _fake_provider()
        await provider.generate_lesson_draft(system_prompt="system", user_prompt="user")
        self.assertEqual(fake_client.chat.completions.calls[-1]["temperature"], 0.4)

    async def test_check_answer_temperature_is_unchanged(self) -> None:
        provider, fake_client = _fake_provider('{"is_correct": true, "feedback": "ok"}')
        await provider.check_answer(english="cat", translation="кот", direction="EN_TO_RU", user_answer="кот")
        self.assertEqual(fake_client.chat.completions.calls[-1]["temperature"], 0)

    async def test_generate_word_translations_temperature_is_unchanged(self) -> None:
        provider, fake_client = _fake_provider("[]")
        await provider.generate_word_translations(words=["cat"])
        self.assertEqual(fake_client.chat.completions.calls[-1]["temperature"], 0)

    async def test_provider_name_identifier(self) -> None:
        self.assertEqual(PolzaAIProvider.name, "polza")


if __name__ == "__main__":
    unittest.main()
