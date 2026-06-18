from __future__ import annotations

import random
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
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

            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                total_cards INTEGER NOT NULL DEFAULT 0,
                remembered_count INTEGER NOT NULL DEFAULT 0,
                forgotten_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_date TEXT NOT NULL,
                sessions_completed INTEGER NOT NULL DEFAULT 0,
                cards_reviewed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, activity_date)
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


    def list_registered_users(self) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM users ORDER BY id")

    def select_game_words(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        rows = self.fetchall(
            """
            SELECT words.*, word_progress.score, word_progress.times_remembered, word_progress.times_forgotten,
                   CASE
                       WHEN word_progress.id IS NULL THEN 'new'
                       WHEN word_progress.score <= 1 OR word_progress.times_forgotten > word_progress.times_remembered THEN 'weak'
                       WHEN word_progress.score >= 2 THEN 'strong'
                       ELSE 'weak'
                   END AS game_category
            FROM words
            LEFT JOIN word_progress ON word_progress.word_id = words.id AND word_progress.user_id = ?
            WHERE words.owner_user_id = ?
            """,
            (user_id, user_id),
        )
        buckets = {"new": [], "weak": [], "strong": []}
        for row in rows:
            buckets[row["game_category"]].append(row)

        for bucket in buckets.values():
            random.shuffle(bucket)

        new_quota = round(limit * 0.50)
        weak_quota = round(limit * 0.35)
        quotas = {"new": new_quota, "weak": weak_quota, "strong": limit - new_quota - weak_quota}
        selected: list[sqlite3.Row] = []
        selected_ids: set[int] = set()
        for category in ("new", "weak", "strong"):
            for row in buckets[category][: quotas[category]]:
                selected.append(row)
                selected_ids.add(int(row["id"]))

        remaining = [
            row
            for category in ("new", "weak", "strong")
            for row in buckets[category]
            if int(row["id"]) not in selected_ids
        ]
        random.shuffle(remaining)
        for row in remaining:
            if len(selected) >= limit:
                break
            selected.append(row)
            selected_ids.add(int(row["id"]))
        random.shuffle(selected)
        return selected[:limit]

    def create_study_session(self, user_id: int, total_cards: int) -> int:
        cursor = self.execute(
            """
            INSERT INTO study_sessions (user_id, started_at, total_cards)
            VALUES (?, ?, ?)
            """,
            (user_id, utc_now(), total_cards),
        )
        return int(cursor.lastrowid)

    def finish_study_session(
        self, session_id: int, remembered_count: int, forgotten_count: int, skipped_count: int, completed: bool
    ) -> None:
        self.execute(
            """
            UPDATE study_sessions
            SET finished_at = ?, remembered_count = ?, forgotten_count = ?, skipped_count = ?, completed = ?
            WHERE id = ?
            """,
            (utc_now(), remembered_count, forgotten_count, skipped_count, int(completed), session_id),
        )

    def update_daily_activity(self, user_id: int, activity_date: date, cards_reviewed: int) -> sqlite3.Row:
        now = utc_now()
        date_text = activity_date.isoformat()
        self.execute(
            """
            INSERT INTO daily_activity (user_id, activity_date, sessions_completed, cards_reviewed, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(user_id, activity_date) DO UPDATE SET
                sessions_completed = sessions_completed + 1,
                cards_reviewed = cards_reviewed + excluded.cards_reviewed,
                updated_at = excluded.updated_at
            """,
            (user_id, date_text, cards_reviewed, now, now),
        )
        row = self.get_daily_activity(user_id, activity_date)
        if row is None:
            raise RuntimeError("Failed to update daily activity")
        return row

    def get_daily_activity(self, user_id: int, activity_date: date) -> sqlite3.Row | None:
        return self.fetchone(
            "SELECT * FROM daily_activity WHERE user_id = ? AND activity_date = ?",
            (user_id, activity_date.isoformat()),
        )

    def has_completed_session_on(self, user_id: int, activity_date: date) -> bool:
        row = self.get_daily_activity(user_id, activity_date)
        return bool(row and row["sessions_completed"] > 0)

    def current_streak(self, user_id: int, today: date) -> int:
        rows = self.fetchall(
            """
            SELECT activity_date FROM daily_activity
            WHERE user_id = ? AND sessions_completed > 0 AND activity_date <= ?
            ORDER BY activity_date DESC
            """,
            (user_id, today.isoformat()),
        )
        streak = 0
        expected = today
        for row in rows:
            activity_day = date.fromisoformat(row["activity_date"])
            if activity_day == expected:
                streak += 1
                expected = date.fromordinal(expected.toordinal() - 1)
            elif activity_day < expected:
                break
        return streak

    def add_word(self, owner_user_id: int, english: str, translation: str, topic: str | None, example: str | None) -> bool:
        english = english.strip()
        translation = translation.strip()
        if self.word_exists(owner_user_id, english):
            return False
        now = utc_now()
        self.execute(
            """
            INSERT INTO words (owner_user_id, english, translation, topic, example, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_user_id, english, translation, topic, example, now, now),
        )
        return True

    def word_exists(self, owner_user_id: int, english: str) -> bool:
        row = self.fetchone(
            "SELECT 1 FROM words WHERE owner_user_id = ? AND lower(english) = lower(?) LIMIT 1",
            (owner_user_id, english.strip()),
        )
        return row is not None

    def get_owned_word(self, word_id: int, owner_user_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            "SELECT * FROM words WHERE id = ? AND owner_user_id = ?",
            (word_id, owner_user_id),
        )

    def delete_word(self, word_id: int, owner_user_id: int) -> bool:
        if self.get_owned_word(word_id, owner_user_id) is None:
            return False
        self.execute("DELETE FROM word_progress WHERE word_id = ?", (word_id,))
        cursor = self.execute(
            "DELETE FROM words WHERE id = ? AND owner_user_id = ?",
            (word_id, owner_user_id),
        )
        return cursor.rowcount > 0

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


    def list_partner_words(self, owner_user_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT words.*, users.display_name AS owner_name
            FROM words JOIN users ON users.id = words.owner_user_id
            WHERE owner_user_id != ?
            ORDER BY words.created_at DESC, words.id DESC
            """,
            (owner_user_id,),
        )

    def copy_word_to_user(self, source_word_id: int, owner_user_id: int) -> bool:
        source = self.fetchone("SELECT * FROM words WHERE id = ?", (source_word_id,))
        if source is None:
            return False
        return self.add_word(owner_user_id, source["english"], source["translation"], source["topic"], source["example"])

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
