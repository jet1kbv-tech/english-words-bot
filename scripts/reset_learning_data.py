"""Reset learning content and progress while keeping users, roles and access.

Deletes dictionaries, progress, game sessions, daily activity and all lesson data
(lessons, lesson words, assignments, homework). Keeps `users`, `student_access`,
`user_tutorials` and `product_notifications` so nobody loses access or their role.

A timestamped backup copy of the SQLite file is always created before any delete.
Reads DATABASE_PATH from .env, same as the seed scripts.

Usage:
    python scripts/reset_learning_data.py          # asks for confirmation
    python scripts/reset_learning_data.py --yes     # no prompt (for automation)
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

# Child tables first so foreign keys never block a delete.
TABLES_TO_CLEAR: tuple[str, ...] = (
    "homework_answers",
    "homework_tasks",
    "lesson_words",
    "lesson_students",
    "lessons",
    "word_progress",
    "study_sessions",
    "daily_activity",
    "words",
)

TABLES_TO_KEEP: tuple[str, ...] = (
    "users",
    "student_access",
    "user_tutorials",
    "product_notifications",
)


def database_path() -> Path:
    load_dotenv()
    return Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3"))


def _count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
    return int(row["total"] if row else 0)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def backup_database(db_path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = db_path.with_name(f"{db_path.name}.backup-{stamp}")
    shutil.copy2(db_path, backup)
    return backup


def main() -> int:
    auto_confirm = "--yes" in sys.argv[1:]
    db_path = database_path()

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    present = [t for t in TABLES_TO_CLEAR if _table_exists(connection, t)]
    before = {table: _count(connection, table) for table in present}

    print(f"Database: {db_path}")
    print("Will DELETE from (content + progress + lessons):")
    for table in present:
        print(f"  - {table}: {before[table]} rows")
    print("Will KEEP:")
    for table in TABLES_TO_KEEP:
        if _table_exists(connection, table):
            print(f"  - {table}: {_count(connection, table)} rows")

    if not auto_confirm:
        answer = input("\nType 'reset' to confirm: ").strip().lower()
        if answer != "reset":
            print("Aborted. Nothing was changed.")
            connection.close()
            return 1

    backup = backup_database(db_path)
    print(f"\nBackup created: {backup}")

    connection.execute("PRAGMA foreign_keys = OFF")
    with connection:
        for table in present:
            connection.execute(f"DELETE FROM {table}")
        # Reset AUTOINCREMENT counters so ids start from 1 again.
        if _table_exists(connection, "sqlite_sequence"):
            placeholders = ",".join("?" for _ in present)
            connection.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", present
            )
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("VACUUM")
    connection.commit()

    after = {table: _count(connection, table) for table in present}
    connection.close()

    print("\nDone. Row counts after reset:")
    for table in present:
        print(f"  - {table}: {after[table]}")
    print(f"\nIf anything looks wrong, restore with:\n  cp {backup} {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
