from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.lesson_metadata import parse_lesson_title


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

            CREATE TABLE IF NOT EXISTS student_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT,
                added_by_user_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
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
                xp_earned INTEGER NOT NULL DEFAULT 0,
                streak_days INTEGER NOT NULL DEFAULT 0,
                day_level TEXT NOT NULL DEFAULT 'Разогрев',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, activity_date)
            );

            CREATE TABLE IF NOT EXISTS lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_user_id INTEGER,
                student_user_id INTEGER,
                title TEXT NOT NULL,
                lesson_number INTEGER,
                topic TEXT,
                description TEXT,
                level TEXT,
                theme TEXT,
                grammar_topic TEXT,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lesson_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(lesson_id, word_id)
            );

            CREATE TABLE IF NOT EXISTS lesson_students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                student_username TEXT NOT NULL,
                assigned_by_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'ASSIGNED',
                is_active INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                unassigned_at TEXT NULL,
                completed_at TEXT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_lesson_students_lesson_id
            ON lesson_students(lesson_id);

            CREATE INDEX IF NOT EXISTS idx_lesson_students_student_username
            ON lesson_students(student_username);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_lesson_students_one_active_per_lesson
            ON lesson_students(lesson_id)
            WHERE is_active = 1;

            CREATE TABLE IF NOT EXISTS homework_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                expected_answer TEXT,
                metadata_json TEXT,
                order_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS homework_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                answer TEXT NOT NULL,
                is_correct INTEGER,
                feedback TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_tutorials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                tutorial_key TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, tutorial_key)
            );

            CREATE TABLE IF NOT EXISTS product_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                role TEXT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                feature_key TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self._connection.commit()
        self._ensure_daily_activity_xp_column()
        self._ensure_lessons_schema()
        self._ensure_lesson_students_schema()
        self._ensure_tutorial_notifications_schema()

    def _ensure_daily_activity_xp_column(self) -> None:
        columns = {row["name"] for row in self.fetchall("PRAGMA table_info(daily_activity)")}
        if "xp_earned" not in columns:
            self.execute("ALTER TABLE daily_activity ADD COLUMN xp_earned INTEGER NOT NULL DEFAULT 0")


    def _ensure_lessons_schema(self) -> None:
        columns = {row["name"]: row for row in self.fetchall("PRAGMA table_info(lessons)")}
        if not columns:
            return
        needs_rebuild = columns.get("student_user_id") is not None and int(columns["student_user_id"]["notnull"]) == 1
        if needs_rebuild:
            self._connection.executescript(
                """
                PRAGMA foreign_keys = OFF;
                ALTER TABLE lessons RENAME TO lessons_old;
                CREATE TABLE lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    teacher_user_id INTEGER,
                    student_user_id INTEGER,
                    title TEXT NOT NULL,
                    lesson_number INTEGER,
                    topic TEXT,
                    description TEXT,
                    level TEXT,
                    theme TEXT,
                    grammar_topic TEXT,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO lessons (id, teacher_user_id, student_user_id, title, lesson_number, topic, description, level, theme, grammar_topic, status, created_at, updated_at)
                SELECT id, teacher_user_id, student_user_id, title, NULL, NULL, NULL, NULL, theme, grammar_topic, upper(status), created_at, updated_at
                FROM lessons_old;
                DROP TABLE lessons_old;
                PRAGMA foreign_keys = ON;
                """
            )
            self._connection.commit()
        else:
            metadata_columns = {
                "lesson_number": "INTEGER NULL",
                "topic": "TEXT NULL",
                "description": "TEXT NULL",
                "level": "TEXT NULL",
            }
            for column_name, column_type in metadata_columns.items():
                if column_name not in columns:
                    self.execute(f"ALTER TABLE lessons ADD COLUMN {column_name} {column_type}")
            self.execute("UPDATE lessons SET status = upper(status) WHERE status != upper(status)")


    def _ensure_lesson_students_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS lesson_students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                student_username TEXT NOT NULL,
                assigned_by_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'ASSIGNED',
                is_active INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                unassigned_at TEXT NULL,
                completed_at TEXT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lesson_students_lesson_id
            ON lesson_students(lesson_id);
            CREATE INDEX IF NOT EXISTS idx_lesson_students_student_username
            ON lesson_students(student_username);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_lesson_students_one_active_per_lesson
            ON lesson_students(lesson_id)
            WHERE is_active = 1;
            """
        )
        self._connection.commit()

    def _ensure_tutorial_notifications_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_tutorials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                tutorial_key TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, tutorial_key)
            );
            CREATE TABLE IF NOT EXISTS product_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                role TEXT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                feature_key TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

    @staticmethod
    def normalize_username(username: str | None) -> str:
        from app.student_access_service import normalize_username

        return normalize_username(username)

    def add_student_access(
        self, username: str, display_name: str | None = None, added_by_user_id: int | None = None
    ) -> sqlite3.Row:
        normalized = self.normalize_username(username)
        if not normalized:
            raise ValueError("username must not be empty")
        now = utc_now()
        self.execute(
            """
            INSERT INTO student_access (username, display_name, added_by_user_id, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                display_name = COALESCE(excluded.display_name, student_access.display_name),
                added_by_user_id = excluded.added_by_user_id,
                is_active = 1,
                updated_at = excluded.updated_at
            """,
            (normalized, display_name, added_by_user_id, now, now),
        )
        row = self.get_student_access(normalized)
        if row is None:
            raise RuntimeError("Failed to create or load student access")
        return row

    def get_student_access(self, username: str) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM student_access WHERE username = ?", (self.normalize_username(username),))

    def is_active_student_access(self, username: str | None) -> bool:
        normalized = self.normalize_username(username)
        if not normalized:
            return False
        row = self.fetchone("SELECT 1 FROM student_access WHERE username = ? AND is_active = 1", (normalized,))
        return row is not None

    def list_student_users(self, usernames: Iterable[str]) -> list[sqlite3.Row]:
        normalized = sorted({self.normalize_username(username) for username in usernames if username})
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        return self.fetchall(
            f"SELECT * FROM users WHERE lower(username) IN ({placeholders}) ORDER BY display_name, username",
            normalized,
        )

    def list_student_targets(self, usernames: Iterable[str], display_names: dict[str, str] | None = None) -> list[dict[str, Any]]:
        display_names = display_names or {}
        target_usernames = {self.normalize_username(username) for username in usernames if username}
        target_usernames.update(
            row["username"] for row in self.fetchall("SELECT username FROM student_access WHERE is_active = 1")
        )
        if not target_usernames:
            return []
        placeholders = ",".join("?" for _ in target_usernames)
        users = {
            self.normalize_username(row["username"]): row
            for row in self.fetchall(f"SELECT * FROM users WHERE lower(username) IN ({placeholders})", sorted(target_usernames))
        }
        access_rows = {
            row["username"]: row
            for row in self.fetchall(
                f"SELECT * FROM student_access WHERE username IN ({placeholders}) AND is_active = 1",
                sorted(target_usernames),
            )
        }
        targets: list[dict[str, Any]] = []
        for username in sorted(target_usernames):
            user = users.get(username)
            access = access_rows.get(username)
            display_name = (
                user["display_name"]
                if user is not None
                else (access["display_name"] if access is not None and access["display_name"] else display_names.get(username, username))
            )
            targets.append({
                "id": user["id"] if user is not None else None,
                "telegram_id": user["telegram_id"] if user is not None else None,
                "username": user["username"] if user is not None else username,
                "display_name": display_name,
                "has_user": user is not None,
            })
        return sorted(targets, key=lambda item: (str(item["display_name"]).casefold(), str(item["username"]).casefold()))

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

    def get_user_by_telegram_id(self, telegram_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))

    def get_user_by_username(self, username: str) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM users WHERE lower(username) = ?", (self.normalize_username(username),))

    def has_completed_tutorial(self, user_id: int, tutorial_key: str) -> bool:
        return self.fetchone("SELECT 1 FROM user_tutorials WHERE user_id = ? AND tutorial_key = ?", (user_id, tutorial_key)) is not None

    def mark_tutorial_completed(self, user_id: int, username: str | None, tutorial_key: str) -> None:
        self.execute(
            """
            INSERT INTO user_tutorials (user_id, username, tutorial_key)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tutorial_key) DO UPDATE SET
                username = excluded.username,
                completed_at = CURRENT_TIMESTAMP
            """,
            (user_id, self.normalize_username(username), tutorial_key),
        )

    def reset_tutorial(self, user_id: int, tutorial_key: str) -> None:
        self.execute("DELETE FROM user_tutorials WHERE user_id = ? AND tutorial_key = ?", (user_id, tutorial_key))

    def create_product_notification(self, key: str, role: str | None, title: str, body: str, feature_key: str | None = None, is_active: bool = True) -> sqlite3.Row:
        self.execute(
            """
            INSERT INTO product_notifications (key, role, title, body, feature_key, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                role = excluded.role, title = excluded.title, body = excluded.body,
                feature_key = excluded.feature_key, is_active = excluded.is_active
            """,
            (key, role, title, body, feature_key, 1 if is_active else 0),
        )
        row = self.fetchone("SELECT * FROM product_notifications WHERE key = ?", (key,))
        if row is None:
            raise RuntimeError("Failed to create product notification")
        return row

    def list_active_product_notifications(self, role: str | None = None) -> list[sqlite3.Row]:
        if role is None:
            return self.fetchall("SELECT * FROM product_notifications WHERE is_active = 1 ORDER BY created_at DESC, id DESC")
        return self.fetchall(
            "SELECT * FROM product_notifications WHERE is_active = 1 AND (role IS NULL OR role = ?) ORDER BY created_at DESC, id DESC",
            (role,),
        )


    def create_teacher_lesson(self, title: str, teacher_user_id: int | None = None) -> sqlite3.Row:
        now = utc_now()
        title = title.strip()
        lesson_number, topic = parse_lesson_title(title)
        cursor = self.execute(
            """
            INSERT INTO lessons (
                teacher_user_id, student_user_id, title, lesson_number, topic, description, level, status, created_at, updated_at
            ) VALUES (?, NULL, ?, ?, ?, NULL, NULL, 'DRAFT', ?, ?)
            """,
            (teacher_user_id, title, lesson_number, topic, now, now),
        )
        lesson = self.get_lesson(int(cursor.lastrowid))
        if lesson is None:
            raise RuntimeError("Failed to create lesson")
        return lesson

    def list_lessons(self) -> list[sqlite3.Row]:
        return self.fetchall("SELECT * FROM lessons ORDER BY created_at DESC, id DESC")

    def get_lesson(self, lesson_id: int) -> sqlite3.Row | None:
        return self.fetchone("SELECT * FROM lessons WHERE id = ?", (lesson_id,))

    def get_lesson_summary(self, lesson_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            """
            SELECT lessons.*,
                   (SELECT COUNT(*) FROM lesson_words WHERE lesson_id = lessons.id) AS words_count,
                   (SELECT COUNT(*) FROM homework_tasks WHERE lesson_id = lessons.id) AS homework_tasks_count,
                   (SELECT COUNT(*) FROM homework_tasks WHERE lesson_id = lessons.id) AS homework_count,
                   0 AS grammar_count,
                   0 AS exercises_count
            FROM lessons
            WHERE lessons.id = ?
            """,
            (lesson_id,),
        )

    def create_lesson(
        self,
        student_user_id: int,
        teacher_user_id: int | None,
        title: str,
        theme: str | None = None,
        grammar_topic: str | None = None,
    ) -> sqlite3.Row:
        now = utc_now()
        cursor = self.execute(
            """
            INSERT INTO lessons (teacher_user_id, student_user_id, title, theme, grammar_topic, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'DRAFT', ?, ?)
            """,
            (teacher_user_id, student_user_id, title, theme, grammar_topic, now, now),
        )
        lesson = self.fetchone("SELECT * FROM lessons WHERE id = ?", (cursor.lastrowid,))
        if lesson is None:
            raise RuntimeError("Failed to create lesson")
        return lesson

    def list_lessons_for_student(self, student_user_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT * FROM lessons
            WHERE student_user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (student_user_id,),
        )

    def list_lessons_for_teacher(self, teacher_user_id: int, limit: int | None = None) -> list[sqlite3.Row]:
        limit_sql = "" if limit is None else "LIMIT ?"
        params: tuple[Any, ...] = (teacher_user_id,) if limit is None else (teacher_user_id, limit)
        return self.fetchall(
            f"""
            SELECT lessons.*, users.display_name AS student_display_name, users.username AS student_username
            FROM lessons
            JOIN users ON users.id = lessons.student_user_id
            WHERE teacher_user_id = ?
            ORDER BY created_at DESC, lessons.id DESC
            {limit_sql}
            """,
            params,
        )




    def list_student_lessons(self, student_username: str) -> list[sqlite3.Row]:
        normalized = self.normalize_username(student_username)
        if not normalized:
            return []
        return self.fetchall(
            """
            SELECT lessons.*, lesson_students.assigned_at AS assigned_at
            FROM lesson_students
            JOIN lessons ON lessons.id = lesson_students.lesson_id
            WHERE lesson_students.student_username = ?
              AND lesson_students.is_active = 1
            ORDER BY lesson_students.assigned_at DESC, lessons.lesson_number ASC, lessons.id ASC
            """,
            (normalized,),
        )

    def get_student_lesson(self, lesson_id: int, student_username: str) -> sqlite3.Row | None:
        normalized = self.normalize_username(student_username)
        if not normalized:
            return None
        return self.fetchone(
            """
            SELECT lessons.*, lesson_students.assigned_at AS assigned_at,
                   (SELECT COUNT(*) FROM lesson_words WHERE lesson_id = lessons.id) AS words_count,
                   (SELECT COUNT(*) FROM homework_tasks WHERE lesson_id = lessons.id) AS homework_tasks_count,
                   (SELECT COUNT(*) FROM homework_tasks WHERE lesson_id = lessons.id) AS homework_count,
                   0 AS grammar_count,
                   0 AS exercises_count
            FROM lesson_students
            JOIN lessons ON lessons.id = lesson_students.lesson_id
            WHERE lessons.id = ?
              AND lesson_students.student_username = ?
              AND lesson_students.is_active = 1
            LIMIT 1
            """,
            (lesson_id, normalized),
        )

    def get_active_lesson_assignment(self, lesson_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            "SELECT * FROM lesson_students WHERE lesson_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (lesson_id,),
        )

    def list_lesson_assignment_history(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM lesson_students WHERE lesson_id = ? ORDER BY id ASC",
            (lesson_id,),
        )

    def assign_lesson_to_student(
        self, lesson_id: int, student_username: str, assigned_by_user_id: int | None = None
    ) -> sqlite3.Row:
        if self.get_lesson(lesson_id) is None:
            raise ValueError("lesson not found")
        normalized = self.normalize_username(student_username)
        if not normalized:
            raise ValueError("student username must not be empty")
        active = self.get_active_lesson_assignment(lesson_id)
        if active is not None and active["student_username"] == normalized:
            return active
        now = utc_now()
        self.execute(
            "UPDATE lesson_students SET is_active = 0, unassigned_at = ? WHERE lesson_id = ? AND is_active = 1",
            (now, lesson_id),
        )
        cursor = self.execute(
            """
            INSERT INTO lesson_students (lesson_id, student_username, assigned_by_user_id, status, is_active, assigned_at)
            VALUES (?, ?, ?, 'ASSIGNED', 1, ?)
            """,
            (lesson_id, normalized, assigned_by_user_id, now),
        )
        row = self.fetchone("SELECT * FROM lesson_students WHERE id = ?", (cursor.lastrowid,))
        if row is None:
            raise RuntimeError("Failed to create lesson assignment")
        return row

    def unassign_lesson(self, lesson_id: int) -> None:
        if self.get_lesson(lesson_id) is None:
            raise ValueError("lesson not found")
        self.execute(
            "UPDATE lesson_students SET is_active = 0, unassigned_at = ? WHERE lesson_id = ? AND is_active = 1",
            (utc_now(), lesson_id),
        )

    def list_lesson_words(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT lesson_words.*, words.english AS text
            FROM lesson_words
            JOIN words ON words.id = lesson_words.word_id
            WHERE lesson_words.lesson_id = ?
            ORDER BY lesson_words.id ASC
            """,
            (lesson_id,),
        )

    def get_lesson_word(self, lesson_id: int, word_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            """
            SELECT words.*, lesson_words.lesson_id AS lesson_id, lesson_words.id AS lesson_word_id
            FROM lesson_words
            JOIN words ON words.id = lesson_words.word_id
            WHERE lesson_words.lesson_id = ? AND lesson_words.word_id = ?
            """,
            (lesson_id, word_id),
        )

    def list_lesson_training_words(self, lesson_id: int, user_id: int) -> list[sqlite3.Row]:
        """Words of a lesson with the given student's progress, for practice.

        Lesson words are owned by the teacher, so this joins on lesson_words
        instead of owner and left-joins the student's own word_progress.
        """
        return self.fetchall(
            """
            SELECT words.*, users.display_name AS owner_name,
                   word_progress.score AS progress_score,
                   word_progress.times_remembered AS times_remembered,
                   word_progress.times_forgotten AS times_forgotten
            FROM lesson_words
            JOIN words ON words.id = lesson_words.word_id
            JOIN users ON users.id = words.owner_user_id
            LEFT JOIN word_progress ON word_progress.word_id = words.id AND word_progress.user_id = ?
            WHERE lesson_words.lesson_id = ?
            ORDER BY lesson_words.id ASC
            """,
            (user_id, lesson_id),
        )

    def add_lesson_words(self, lesson_id: int, words: list[str], owner_user_id: int | None = None) -> list[sqlite3.Row]:
        lesson = self.get_lesson(lesson_id)
        if lesson is None:
            raise ValueError("lesson not found")
        owner_id = owner_user_id or lesson["teacher_user_id"] or lesson["student_user_id"]
        if owner_id is None:
            raise ValueError("word owner is required")
        created_word_ids: list[int] = []
        now = utc_now()
        for word in words:
            cursor = self.execute(
                """
                INSERT INTO words (owner_user_id, english, translation, topic, example, created_at, updated_at)
                VALUES (?, ?, '', NULL, NULL, ?, ?)
                """,
                (owner_id, word, now, now),
            )
            word_id = int(cursor.lastrowid)
            created_word_ids.append(word_id)
            self.execute(
                """
                INSERT INTO lesson_words (lesson_id, word_id, created_at)
                VALUES (?, ?, ?)
                """,
                (lesson_id, word_id, now),
            )
        return self.list_lesson_words(lesson_id)[-len(created_word_ids):]

    def add_word_to_lesson(self, lesson_id: int, word_id: int) -> bool:
        cursor = self.execute(
            """
            INSERT OR IGNORE INTO lesson_words (lesson_id, word_id, created_at)
            VALUES (?, ?, ?)
            """,
            (lesson_id, word_id, utc_now()),
        )
        return cursor.rowcount > 0

    def add_homework_task(
        self,
        lesson_id: int,
        task_type: str,
        prompt: str,
        expected_answer: str | None = None,
        metadata_json: str | None = None,
        order_index: int = 0,
    ) -> sqlite3.Row:
        now = utc_now()
        cursor = self.execute(
            """
            INSERT INTO homework_tasks (
                lesson_id, task_type, prompt, expected_answer, metadata_json, order_index, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lesson_id, task_type, prompt, expected_answer, metadata_json, order_index, now, now),
        )
        task = self.fetchone("SELECT * FROM homework_tasks WHERE id = ?", (cursor.lastrowid,))
        if task is None:
            raise RuntimeError("Failed to create homework task")
        return task

    def list_homework_tasks(self, lesson_id: int) -> list[sqlite3.Row]:
        return self.fetchall(
            "SELECT * FROM homework_tasks WHERE lesson_id = ? ORDER BY order_index ASC, id ASC",
            (lesson_id,),
        )

    def get_homework_task(self, lesson_id: int, task_id: int) -> sqlite3.Row | None:
        return self.fetchone(
            "SELECT * FROM homework_tasks WHERE id = ? AND lesson_id = ?",
            (task_id, lesson_id),
        )

    def delete_homework_task(self, lesson_id: int, task_id: int) -> bool:
        if self.get_homework_task(lesson_id, task_id) is None:
            return False
        self.execute("DELETE FROM homework_answers WHERE task_id = ?", (task_id,))
        cursor = self.execute(
            "DELETE FROM homework_tasks WHERE id = ? AND lesson_id = ?",
            (task_id, lesson_id),
        )
        return cursor.rowcount > 0

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

    def update_lesson_word_field(self, lesson_id: int, word_id: int, field: str, value: str | None) -> bool:
        if field not in {"translation", "example", "topic"}:
            raise ValueError("unsupported word field")
        if self.get_lesson_word(lesson_id, word_id) is None:
            return False
        cursor = self.execute(
            f"UPDATE words SET {field} = ?, updated_at = ? WHERE id = ?",
            (value, utc_now(), word_id),
        )
        return cursor.rowcount > 0

    def update_word_translation(self, lesson_id: int, word_id: int, value: str | None) -> bool:
        return self.update_lesson_word_field(lesson_id, word_id, "translation", value)

    def update_word_example(self, lesson_id: int, word_id: int, value: str | None) -> bool:
        return self.update_lesson_word_field(lesson_id, word_id, "example", value)

    def update_word_topic(self, lesson_id: int, word_id: int, value: str | None) -> bool:
        return self.update_lesson_word_field(lesson_id, word_id, "topic", value)

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
            SELECT words.*, users.display_name AS owner_name,
                   word_progress.score AS progress_score,
                   word_progress.times_remembered AS times_remembered,
                   word_progress.times_forgotten AS times_forgotten
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

    def correct_forgotten_to_remembered(self, user_id: int, word_id: int) -> None:
        """Turn one already-counted negative answer into a positive answer.

        The card was already marked as seen by update_progress(..., False), so this
        correction intentionally leaves times_seen unchanged.
        """
        now = utc_now()
        self.execute(
            """
            UPDATE word_progress
            SET score = score + 2,
                times_remembered = times_remembered + 1,
                times_forgotten = MAX(times_forgotten - 1, 0),
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
            return "Легенда дня"
        if cards_reviewed >= 20:
            return "Сильный день"
        if cards_reviewed >= 10:
            return "Цель выполнена"
        return "Разогрев"

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
        xp_earned: int = 0,
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
                skipped_cards, xp_earned, streak_days, day_level, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, activity_date) DO UPDATE SET
                cards_reviewed = cards_reviewed + excluded.cards_reviewed,
                known_cards = known_cards + excluded.known_cards,
                unknown_cards = unknown_cards + excluded.unknown_cards,
                skipped_cards = skipped_cards + excluded.skipped_cards,
                xp_earned = xp_earned + excluded.xp_earned,
                streak_days = excluded.streak_days,
                updated_at = excluded.updated_at
            """,
            (
                user_id, activity_date, cards_reviewed, known_cards, unknown_cards,
                skipped_cards, xp_earned, base_streak, "Разогрев", now, now,
            ),
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

    def list_weak_words(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self.fetchall(
            """
            SELECT words.*,
                   COALESCE(word_progress.score, 0) AS progress_score,
                   COALESCE(word_progress.times_forgotten, 0) AS times_forgotten,
                   COALESCE(word_progress.times_remembered, 0) AS times_remembered
            FROM words
            LEFT JOIN word_progress ON word_progress.word_id = words.id AND word_progress.user_id = ?
            WHERE words.owner_user_id = ?
            ORDER BY progress_score ASC, times_forgotten DESC, times_remembered ASC, words.created_at DESC
            LIMIT ?
            """,
            (user_id, user_id, limit),
        )
