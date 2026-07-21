"""Print configured roles and how each known user resolves.

Verifies the role setup: configured admin/teacher/student usernames from
`load_settings()`, then every row in `users` and every active `student_access`
entry with the role `RoleResolver` assigns to it.

Reads DATABASE_PATH from .env. If BOT_TOKEN is missing (e.g. running locally),
a placeholder is set only so `load_settings()` does not refuse to build; the
token itself is never used by this report.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_settings():
    load_dotenv()
    if not os.getenv("BOT_TOKEN"):
        os.environ["BOT_TOKEN"] = "placeholder-for-report"
    from app.config import load_settings

    return load_settings()


def main() -> int:
    settings = _load_settings()
    from app.auth.roles import RoleResolver

    resolver = RoleResolver(settings)

    print("=== Configured roles ===")
    for username in sorted(settings.admin_usernames):
        print(f"  ADMIN    @{username}  ({settings.display_names.get(username, '—')})")
    for username in sorted(settings.teacher_usernames):
        print(f"  TEACHER  @{username}  ({settings.display_names.get(username, '—')})")
    for username in sorted(settings.allowed_usernames):
        print(f"  STUDENT  @{username}  ({settings.display_names.get(username, '—')})")

    db_path = Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3"))
    if not db_path.exists():
        print(f"\nDatabase not found ({db_path}); skipping DB users report.")
        return 0

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    print("\n=== Registered users (from /start) ===")
    users = connection.execute(
        "SELECT username, display_name, telegram_id FROM users ORDER BY id"
    ).fetchall()
    if not users:
        print("  (no users have opened /start yet)")
    for row in users:
        role = resolver.role_for(row["username"]).name
        print(f"  {role:8} @{row['username']}  ({row['display_name']})  tg={row['telegram_id']}")

    print("\n=== Active student_access (added from the bot) ===")
    access = connection.execute(
        "SELECT username, display_name FROM student_access WHERE is_active = 1 ORDER BY username"
    ).fetchall()
    if not access:
        print("  (none)")
    for row in access:
        role = resolver.role_for(row["username"]).name
        label = row["display_name"] or "—"
        print(f"  {role:8} @{row['username']}  ({label})")

    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
