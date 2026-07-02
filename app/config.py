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
    admin_usernames: frozenset[str]
    teacher_usernames: frozenset[str]
    display_names: dict[str, str]


def _parse_usernames(value: str) -> frozenset[str]:
    return frozenset(username.strip().lstrip("@").lower() for username in value.replace(";", ",").split(",") if username.strip())


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required. Create .env from .env.example and set the token.")

    default_allowed_usernames = "wp_bvv,privetnormalno"
    allowed_usernames = _parse_usernames(os.getenv("ALLOWED_USERNAMES", default_allowed_usernames))
    admin_usernames = _parse_usernames(os.getenv("ADMIN_USERNAMES", ""))
    teacher_usernames = _parse_usernames(os.getenv("TEACHER_USERNAMES", ""))

    return Settings(
        bot_token=token,
        database_path=Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        allowed_usernames=allowed_usernames | admin_usernames | teacher_usernames,
        admin_usernames=admin_usernames,
        teacher_usernames=teacher_usernames,
        display_names={"wp_bvv": "Вова", "privetnormalno": "Саша"},
    )
