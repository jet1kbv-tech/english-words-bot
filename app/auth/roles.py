from __future__ import annotations

from enum import Enum
from typing import Any


class Role(Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


def _normalize_username(username: str | None) -> str:
    return (username or "").lstrip("@").casefold()


def _normalized_config_usernames(config: Any, attr_name: str) -> set[str]:
    usernames = getattr(config, attr_name, frozenset())
    return {_normalize_username(username) for username in usernames}


def get_user_role(username: str | None, config: Any) -> Role:
    normalized_username = _normalize_username(username)
    if normalized_username in _normalized_config_usernames(config, "admin_usernames"):
        return Role.ADMIN
    if normalized_username in _normalized_config_usernames(config, "teacher_usernames"):
        return Role.TEACHER
    return Role.STUDENT


def is_user_allowed(username: str | None, config: Any) -> bool:
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return False

    allowed_usernames = _normalized_config_usernames(config, "allowed_usernames")
    admin_usernames = _normalized_config_usernames(config, "admin_usernames")
    teacher_usernames = _normalized_config_usernames(config, "teacher_usernames")
    return normalized_username in allowed_usernames | admin_usernames | teacher_usernames
