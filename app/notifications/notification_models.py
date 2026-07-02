from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductNotification:
    key: str
    role: str | None
    title: str
    body: str
    feature_key: str | None = None
    is_active: bool = True
