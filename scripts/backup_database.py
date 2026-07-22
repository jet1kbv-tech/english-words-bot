"""Create and verify a backup of the production SQLite database before deploy.

Uses SQLite's online backup API (sqlite3.Connection.backup) instead of a
plain file copy, so a backup taken while the bot service is still running
(mid write) is still a consistent snapshot. Reads DATABASE_PATH from .env,
same convention as scripts/reset_learning_data.py and app/config.py.

Exits non-zero and prints why if the source database is missing, the backup
can't be created, or `PRAGMA integrity_check` on the resulting backup file
does not report exactly "ok". The deploy workflow runs this under `set -e`
before touching the code checkout or restarting the service, so any failure
here stops the deploy immediately: no git reset, no restart, current
production keeps running.

Usage:
    python scripts/backup_database.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

BACKUP_SUBDIR = "backups"


def database_path() -> Path:
    # find_dotenv(usecwd=True): find .env starting from the process's current
    # working directory, not from this file's own location (load_dotenv()'s
    # default). The deploy workflow copies this script out to a temp path
    # (see .github/workflows/deploy.yml) and runs it before the repo checkout
    # is updated, so the default file-location search would look next to
    # /tmp and never find /opt/english-words-bot/.env. Running with cwd
    # already set to the project directory (as the deploy script does) makes
    # this reliable regardless of where the script file itself lives.
    load_dotenv(find_dotenv(usecwd=True))
    return Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3"))


def backup_path_for(db_path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_dir = db_path.resolve().parent / BACKUP_SUBDIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / f"{db_path.name}.pre-deploy-{stamp}"


def create_backup(db_path: Path, backup_path: Path) -> None:
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def verify_integrity(backup_path: Path) -> str:
    connection = sqlite3.connect(backup_path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "no result from PRAGMA integrity_check"
    finally:
        connection.close()


def main() -> int:
    db_path = database_path()

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    backup_path = backup_path_for(db_path)
    print(f"Database: {db_path}")
    print(f"Backing up to: {backup_path}")

    try:
        create_backup(db_path, backup_path)
    except sqlite3.Error as error:
        print(f"Backup failed: {error}")
        return 1

    try:
        result = verify_integrity(backup_path)
    except sqlite3.Error as error:
        print(f"Integrity check could not run: {error}")
        return 1

    if result != "ok":
        print(f"Integrity check failed: {result}")
        print(f"Backup file left in place for inspection: {backup_path}")
        return 1

    print("Integrity check: ok")
    print(f"Backup verified: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
