from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Fallback values, used only when the corresponding env var is not set at all.
# They match the values this module hardcoded before ALLOWED_USERNAMES /
# ADMIN_USERNAMES / TEACHER_USERNAMES / DISPLAY_NAMES were read from the
# environment, so existing deployments without these vars keep working exactly
# as before.
DEFAULT_ALLOWED_USERNAMES = "privetnormalno"
DEFAULT_ADMIN_USERNAMES = "wp_bvv"
DEFAULT_TEACHER_USERNAMES = "romateaches"
DEFAULT_DISPLAY_NAMES = "wp_bvv:Вова,privetnormalno:Саша,romateaches:Roma"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: Path
    log_level: str
    allowed_usernames: frozenset[str]
    admin_usernames: frozenset[str]
    teacher_usernames: frozenset[str]
    display_names: dict[str, str]


def _normalize_username(username: str) -> str:
    return username.strip().lstrip("@").casefold()


def _parse_usernames(value: str) -> frozenset[str]:
    return frozenset(normalized for part in value.split(",") if (normalized := _normalize_username(part)))


def _parse_display_names(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in value.split(","):
        username, _sep, display_name = part.partition(":")
        username = _normalize_username(username)
        display_name = display_name.strip()
        if username and display_name:
            result[username] = display_name
    return result


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required. Create .env from .env.example and set the token.")

    return Settings(
        bot_token=token,
        database_path=Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        allowed_usernames=_parse_usernames(os.getenv("ALLOWED_USERNAMES", DEFAULT_ALLOWED_USERNAMES)),
        admin_usernames=_parse_usernames(os.getenv("ADMIN_USERNAMES", DEFAULT_ADMIN_USERNAMES)),
        teacher_usernames=_parse_usernames(os.getenv("TEACHER_USERNAMES", DEFAULT_TEACHER_USERNAMES)),
        display_names=_parse_display_names(os.getenv("DISPLAY_NAMES", DEFAULT_DISPLAY_NAMES)),
    )
