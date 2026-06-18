from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: Path
    log_level: str
    allowed_usernames: frozenset[str]
    display_names: dict[str, str]


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required. Create .env from .env.example and set the token.")

    return Settings(
        bot_token=token,
        database_path=Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        allowed_usernames=frozenset({"wp_bvv", "privetnormalno"}),
        display_names={"wp_bvv": "Вова", "privetnormalno": "Саша"},
    )
