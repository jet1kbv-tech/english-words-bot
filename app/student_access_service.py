from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database import Database

_USERNAME_RE = re.compile(r"^[a-z0-9_]{5,32}$")

AddStudentAccessStatus = Literal["created", "already_active", "reactivated"]


@dataclass(frozen=True)
class AddStudentAccessResult:
    username: str
    status: AddStudentAccessStatus


def normalize_username(raw: str | None) -> str:
    return (raw or "").strip().lstrip("@").casefold()


def validate_username(username: str) -> bool:
    return bool(_USERNAME_RE.fullmatch(username))


class StudentAccessService:
    def __init__(self, db: "Database") -> None:
        self.db = db

    def normalize_username(self, raw: str | None) -> str:
        return normalize_username(raw)

    def validate_username(self, username: str) -> bool:
        return validate_username(username)

    def add_student_access(
        self,
        username: str,
        added_by_user_id: int | None,
        display_name: str | None = None,
    ) -> AddStudentAccessResult:
        normalized = normalize_username(username)
        if not validate_username(normalized):
            raise ValueError("invalid Telegram username")

        existing = self.db.get_student_access(normalized)
        if existing is not None and int(existing["is_active"]) == 1:
            return AddStudentAccessResult(username=normalized, status="already_active")

        self.db.add_student_access(normalized, display_name=display_name, added_by_user_id=added_by_user_id)
        return AddStudentAccessResult(username=normalized, status="reactivated" if existing is not None else "created")

    def is_student_access_active(self, username: str | None) -> bool:
        return self.db.is_active_student_access(username)

    def list_active_student_access(self):
        return self.db.fetchall("SELECT * FROM student_access WHERE is_active = 1 ORDER BY username")
