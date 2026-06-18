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

            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                total_cards INTEGER NOT NULL,
                known_cards INTEGER NOT NULL DEFAULT 0,
                unknown_cards INTEGER NOT NULL DEFAULT 0,
                skipped_cards INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_date TEXT NOT NULL,
                cards_reviewed INTEGER NOT NULL DEFAULT 0,
                known_cards INTEGER NOT NULL DEFAULT 0,
                unknown_cards INTEGER NOT NULL DEFAULT 0,
                skipped_cards INTEGER NOT NULL DEFAULT 0,
                streak_days INTEGER NOT NULL DEFAULT 0,
                day_level TEXT NOT NULL DEFAULT 'Новичок',
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


    def list_users(self) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM users ORDER BY id")

    def get_user_by_telegram_id(self, telegram_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))

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

    def list_training_words(self, user_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT words.*, users.display_name AS owner_name, word_progress.score AS progress_score
            FROM words
            JOIN users ON users.id = words.owner_user_id
            LEFT JOIN word_progress ON word_progress.word_id = words.id AND word_progress.user_id = ?
            WHERE words.owner_user_id = ?
            ORDER BY words.created_at DESC, words.id DESC
            """,
            (user_id, user_id),
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

    def list_partner_training_words(self, user_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT words.*, users.display_name AS owner_name, word_progress.score AS progress_score
            FROM words
            JOIN users ON users.id = words.owner_user_id
            LEFT JOIN word_progress ON word_progress.word_id = words.id AND word_progress.user_id = ?
            WHERE words.owner_user_id != ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM words AS own_words
                  WHERE own_words.owner_user_id = ?
                    AND lower(own_words.english) = lower(words.english)
              )
            ORDER BY words.created_at DESC, words.id DESC
            """,
            (user_id, user_id, user_id),
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

    def correct_remembered_to_forgotten(self, user_id: int, word_id: int) -> None:
        """Turn one already-counted positive answer into a negative answer.

        The card was already marked as seen by update_progress(..., True), so this
        correction intentionally leaves times_seen unchanged.
        """
        now = utc_now()
        self.execute(
            """
            UPDATE word_progress
            SET score = MAX(score - 2, 0),
                times_remembered = MAX(times_remembered - 1, 0),
                times_forgotten = times_forgotten + 1,
                updated_at = ?
            WHERE user_id = ? AND word_id = ?
            """,
            (now, user_id, word_id),
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


    def start_study_session(self, user_id: int, total_cards: int) -> int:
        now = utc_now()
        cursor = self.execute(
            """
            INSERT INTO study_sessions (user_id, total_cards, started_at)
            VALUES (?, ?, ?)
            """,
            (user_id, total_cards, now),
        )
        return int(cursor.lastrowid)

    def finish_study_session(self, session_id: int, known_cards: int, unknown_cards: int, skipped_cards: int) -> None:
        self.execute(
            """
            UPDATE study_sessions
            SET known_cards = ?, unknown_cards = ?, skipped_cards = ?, finished_at = ?
            WHERE id = ?
            """,
            (known_cards, unknown_cards, skipped_cards, utc_now(), session_id),
        )

    def day_level(self, cards_reviewed: int) -> str:
        if cards_reviewed >= 30:
            return "Легенда"
        if cards_reviewed >= 20:
            return "Профи"
        if cards_reviewed >= 10:
            return "Разогрев"
        if cards_reviewed > 0:
            return "Старт"
        return "Новичок"

    def _previous_date(self, activity_date: str) -> str:
        from datetime import date, timedelta

        return (date.fromisoformat(activity_date) - timedelta(days=1)).isoformat()

    def record_daily_activity(
        self,
        user_id: int,
        activity_date: str,
        cards_reviewed: int,
        known_cards: int,
        unknown_cards: int,
        skipped_cards: int,
    ) -> sqlite3.Row:
        now = utc_now()
        previous = self.get_daily_activity(user_id, self._previous_date(activity_date))
        current = self.get_daily_activity(user_id, activity_date)
        previous_streak = int(previous["streak_days"]) if previous else 0
        base_streak = int(current["streak_days"]) if current else previous_streak + 1
        self.execute(
            """
            INSERT INTO daily_activity (
                user_id, activity_date, cards_reviewed, known_cards, unknown_cards,
                skipped_cards, streak_days, day_level, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, activity_date) DO UPDATE SET
                cards_reviewed = cards_reviewed + excluded.cards_reviewed,
                known_cards = known_cards + excluded.known_cards,
                unknown_cards = unknown_cards + excluded.unknown_cards,
                skipped_cards = skipped_cards + excluded.skipped_cards,
                streak_days = excluded.streak_days,
                updated_at = excluded.updated_at
            """,
            (user_id, activity_date, cards_reviewed, known_cards, unknown_cards, skipped_cards, base_streak, "Новичок", now, now),
        )
        row = self.get_daily_activity(user_id, activity_date)
        if row is None:
            raise RuntimeError("Failed to record daily activity")
        level = self.day_level(int(row["cards_reviewed"]))
        self.execute(
            "UPDATE daily_activity SET day_level = ?, updated_at = ? WHERE id = ?",
            (level, utc_now(), row["id"]),
        )
        refreshed = self.get_daily_activity(user_id, activity_date)
        if refreshed is None:
            raise RuntimeError("Failed to load daily activity")
        return refreshed

    def get_daily_activity(self, user_id: int, activity_date: str) -> sqlite3.Row | None:
        return self.fetchone(
            "SELECT * FROM daily_activity WHERE user_id = ? AND activity_date = ?",
            (user_id, activity_date),
        )
