from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True) if self.path.parent != Path(".") else None
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self._connection.close()

    def init_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                username TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                english TEXT NOT NULL,
                translation TEXT NOT NULL,
                topic TEXT,
                example TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS word_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                times_seen INTEGER NOT NULL DEFAULT 0,
                times_remembered INTEGER NOT NULL DEFAULT 0,
                times_forgotten INTEGER NOT NULL DEFAULT 0,
                last_reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
                UNIQUE(user_id, word_id)
            );
            """
        )
        self._connection.commit()

    def execute(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cursor = self._connection.execute(query, tuple(params))
        self._connection.commit()
        return cursor

    def fetchone(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self._connection.execute(query, tuple(params)).fetchone()

    def fetchall(self, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self._connection.execute(query, tuple(params)).fetchall())

    def upsert_user(self, telegram_id: int, username: str, display_name: str) -> sqlite3.Row:
        now = utc_now()
        self.execute(
            """
            INSERT INTO users (telegram_id, username, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                updated_at = excluded.updated_at
            """,
            (telegram_id, username, display_name, now, now),
        )
        user = self.get_user_by_telegram_id(telegram_id)
        if user is None:
            raise RuntimeError("Failed to create or load user")
        return user

    def get_user_by_telegram_id(self, telegram_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))

    def add_word(self, owner_user_id: int, english: str, translation: str, topic: str | None, example: str | None) -> None:
        now = utc_now()
        self.execute(
            """
            INSERT INTO words (owner_user_id, english, translation, topic, example, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_user_id, english, translation, topic, example, now, now),
        )

    def list_words(self, owner_user_id: int | None = None) -> list[sqlite3.Row]:
        if owner_user_id is None:
            return self.fetchall(
                """
                SELECT words.*, users.display_name AS owner_name
                FROM words JOIN users ON users.id = words.owner_user_id
                ORDER BY words.created_at DESC, words.id DESC
                """
            )
        return self.fetchall(
            """
            SELECT words.*, users.display_name AS owner_name
            FROM words JOIN users ON users.id = words.owner_user_id
            WHERE owner_user_id = ?
            ORDER BY words.created_at DESC, words.id DESC
            """,
            (owner_user_id,),
        )

    def count_words(self, owner_user_id: int | None = None) -> int:
        if owner_user_id is None:
            row = self.fetchone("SELECT COUNT(*) AS total FROM words")
        else:
            row = self.fetchone("SELECT COUNT(*) AS total FROM words WHERE owner_user_id = ?", (owner_user_id,))
        return int(row["total"] if row else 0)

    def progress_summary(self, user_id: int) -> sqlite3.Row:
        return self.fetchone(
            """
            SELECT COUNT(*) AS trained_cards, COALESCE(AVG(score), 0) AS average_score
            FROM word_progress
            WHERE user_id = ? AND times_seen > 0
            """,
            (user_id,),
        )

    def update_progress(self, user_id: int, word_id: int, remembered: bool | None) -> None:
        now = utc_now()
        self.execute(
            """
            INSERT INTO word_progress (user_id, word_id, score, times_seen, times_remembered, times_forgotten, last_reviewed_at, created_at, updated_at)
            VALUES (?, ?, 0, 0, 0, 0, NULL, ?, ?)
            ON CONFLICT(user_id, word_id) DO NOTHING
            """,
            (user_id, word_id, now, now),
        )
        if remembered is True:
            score_sql = "score + 1"
            remembered_inc = 1
            forgotten_inc = 0
        elif remembered is False:
            score_sql = "MAX(score - 1, 0)"
            remembered_inc = 0
            forgotten_inc = 1
        else:
            score_sql = "score"
            remembered_inc = 0
            forgotten_inc = 0
        self.execute(
            f"""
            UPDATE word_progress
            SET score = {score_sql},
                times_seen = times_seen + 1,
                times_remembered = times_remembered + ?,
                times_forgotten = times_forgotten + ?,
                last_reviewed_at = ?,
                updated_at = ?
            WHERE user_id = ? AND word_id = ?
            """,
            (remembered_inc, forgotten_inc, now, now, user_id, word_id),
        )
