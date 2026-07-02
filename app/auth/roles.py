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


class RoleResolver:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.admin_usernames = _normalized_config_usernames(config, "admin_usernames")
        self.teacher_usernames = _normalized_config_usernames(config, "teacher_usernames")
        self.allowed_usernames = _normalized_config_usernames(config, "allowed_usernames")

    def role_for(self, username: str | None) -> Role:
        normalized_username = _normalize_username(username)
        if normalized_username in self.admin_usernames:
            return Role.ADMIN
        if normalized_username in self.teacher_usernames:
            return Role.TEACHER
        return Role.STUDENT

    def is_allowed(self, username: str | None) -> bool:
        normalized_username = _normalize_username(username)
        if not normalized_username:
            return False
        return normalized_username in self.allowed_usernames | self.admin_usernames | self.teacher_usernames

    @property
    def student_usernames(self) -> set[str]:
        return self.allowed_usernames - self.admin_usernames - self.teacher_usernames


def get_user_role(username: str | None, config: Any) -> Role:
    return RoleResolver(config).role_for(username)


def is_user_allowed(username: str | None, config: Any) -> bool:
    return RoleResolver(config).is_allowed(username)
