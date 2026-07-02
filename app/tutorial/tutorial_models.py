from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TutorialStep:
    title: str
    text: str
    button_text: str | None = None
    feature_key: str | None = None


@dataclass(frozen=True)
class Tutorial:
    key: str
    role: str
    title: str
    steps: list[TutorialStep]
