from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.database import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.user = self.db.upsert_user(1, "tester", "Tester")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_add_word(self) -> None:
        added = self.db.add_word(self.user["id"], "receipt", "чек", None, None)

        self.assertTrue(added)
        words = self.db.list_words(self.user["id"])
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["english"], "receipt")

    def test_duplicate_word_is_not_added_for_same_user(self) -> None:
        self.assertTrue(self.db.add_word(self.user["id"], "receipt", "чек", None, None))
        self.assertFalse(self.db.add_word(self.user["id"], "Receipt", "квитанция", None, None))

        words = self.db.list_words(self.user["id"])
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["translation"], "чек")

    def test_delete_word(self) -> None:
        self.db.add_word(self.user["id"], "deadline", "дедлайн", None, None)
        word = self.db.list_words(self.user["id"])[0]

        deleted = self.db.delete_word(word["id"], self.user["id"])

        self.assertTrue(deleted)
        self.assertEqual(self.db.list_words(self.user["id"]), [])

    def test_delete_word_removes_word_progress(self) -> None:
        self.db.add_word(self.user["id"], "appointment", "встреча", None, None)
        word = self.db.list_words(self.user["id"])[0]
        self.db.update_progress(self.user["id"], word["id"], remembered=True)

        self.assertTrue(self.db.delete_word(word["id"], self.user["id"]))
        progress = self.db.fetchall("SELECT * FROM word_progress WHERE word_id = ?", (word["id"],))
        self.assertEqual(progress, [])


if __name__ == "__main__":
    unittest.main()

class StudySessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.user = self.db.upsert_user(2, "player", "Player")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_study_session_and_daily_activity(self) -> None:
        session_id = self.db.start_study_session(self.user["id"], 10)
        self.db.finish_study_session(session_id, known_cards=7, unknown_cards=2, skipped_cards=1)

        session = self.db.fetchone("SELECT * FROM study_sessions WHERE id = ?", (session_id,))
        self.assertEqual(session["known_cards"], 7)
        self.assertIsNotNone(session["finished_at"])

        activity = self.db.record_daily_activity(self.user["id"], "2026-06-18", 10, 7, 2, 1)
        self.assertEqual(activity["cards_reviewed"], 10)
        self.assertEqual(activity["streak_days"], 1)
        self.assertEqual(activity["day_level"], "Цель выполнена")
        self.assertEqual(activity["xp_earned"], 0)

    def test_daily_activity_accumulates_xp(self) -> None:
        first = self.db.record_daily_activity(self.user["id"], "2026-06-18", 7, 5, 2, 0, 75)
        self.assertEqual(first["xp_earned"], 75)
        self.assertEqual(first["day_level"], "Разогрев")

        second = self.db.record_daily_activity(self.user["id"], "2026-06-18", 3, 2, 1, 0, 49)
        self.assertEqual(second["cards_reviewed"], 10)
        self.assertEqual(second["xp_earned"], 124)
        self.assertEqual(second["day_level"], "Цель выполнена")

class ProgressCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.user = self.db.upsert_user(3, "corrector", "Corrector")
        self.db.add_word(self.user["id"], "awkward", "неловкий", None, None)
        self.word = self.db.list_words(self.user["id"])[0]

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_correct_remembered_to_forgotten_does_not_increment_seen_again(self) -> None:
        self.db.update_progress(self.user["id"], self.word["id"], remembered=True)

        self.db.correct_remembered_to_forgotten(self.user["id"], self.word["id"])

        progress = self.db.fetchone(
            "SELECT * FROM word_progress WHERE user_id = ? AND word_id = ?",
            (self.user["id"], self.word["id"]),
        )
        self.assertEqual(progress["score"], 0)
        self.assertEqual(progress["times_seen"], 1)
        self.assertEqual(progress["times_remembered"], 0)
        self.assertEqual(progress["times_forgotten"], 1)

class ForgottenCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.user = self.db.upsert_user(4, "typo", "Typo")
        self.db.add_word(self.user["id"], "receipt", "чек", None, None)
        self.word = self.db.list_words(self.user["id"])[0]

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_correct_forgotten_to_remembered_does_not_increment_seen_again(self) -> None:
        self.db.update_progress(self.user["id"], self.word["id"], remembered=False)

        self.db.correct_forgotten_to_remembered(self.user["id"], self.word["id"])

        progress = self.db.fetchone(
            "SELECT * FROM word_progress WHERE user_id = ? AND word_id = ?",
            (self.user["id"], self.word["id"]),
        )
        self.assertEqual(progress["score"], 2)
        self.assertEqual(progress["times_seen"], 1)
        self.assertEqual(progress["times_remembered"], 1)
        self.assertEqual(progress["times_forgotten"], 0)

class TeacherDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.student = self.db.upsert_user(10, "StudentOne", "Student One")
        self.teacher = self.db.upsert_user(11, "teacher", "Teacher")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_list_student_users_filters_to_allowed_student_usernames(self) -> None:
        students = self.db.list_student_users({"studentone"})

        self.assertEqual([student["username"] for student in students], ["StudentOne"])

    def test_list_weak_words_orders_low_score_and_forgotten_first(self) -> None:
        self.db.add_word(self.student["id"], "easy", "лёгкий", None, None)
        self.db.add_word(self.student["id"], "hard", "сложный", None, None)
        words = {word["english"]: word for word in self.db.list_words(self.student["id"])}
        self.db.update_progress(self.student["id"], words["easy"]["id"], remembered=True)
        self.db.update_progress(self.student["id"], words["hard"]["id"], remembered=False)

        weak_words = self.db.list_weak_words(self.student["id"], limit=10)

        self.assertEqual(weak_words[0]["english"], "hard")


class LessonDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.student = self.db.upsert_user(20, "student", "Student")
        self.teacher = self.db.upsert_user(21, "teacher", "Teacher")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_create_lesson_creates_lesson(self) -> None:
        lesson = self.db.create_lesson(
            self.student["id"],
            self.teacher["id"],
            "Past Simple",
            theme="Travel",
            grammar_topic="Past Simple",
        )

        self.assertEqual(lesson["student_user_id"], self.student["id"])
        self.assertEqual(lesson["teacher_user_id"], self.teacher["id"])
        self.assertEqual(lesson["title"], "Past Simple")
        self.assertEqual(lesson["theme"], "Travel")
        self.assertEqual(lesson["grammar_topic"], "Past Simple")
        self.assertEqual(lesson["status"], "draft")

    def test_list_lessons_for_student_returns_student_lessons(self) -> None:
        other_student = self.db.upsert_user(22, "other", "Other")
        lesson = self.db.create_lesson(self.student["id"], self.teacher["id"], "Lesson A")
        self.db.create_lesson(other_student["id"], self.teacher["id"], "Lesson B")

        lessons = self.db.list_lessons_for_student(self.student["id"])

        self.assertEqual([row["id"] for row in lessons], [lesson["id"]])

    def test_list_lessons_for_teacher_returns_teacher_lessons(self) -> None:
        other_teacher = self.db.upsert_user(23, "otherteacher", "Other Teacher")
        lesson = self.db.create_lesson(self.student["id"], self.teacher["id"], "Lesson A")
        self.db.create_lesson(self.student["id"], other_teacher["id"], "Lesson B")

        lessons = self.db.list_lessons_for_teacher(self.teacher["id"])

        self.assertEqual([row["id"] for row in lessons], [lesson["id"]])

    def test_add_word_to_lesson_does_not_create_duplicate(self) -> None:
        lesson = self.db.create_lesson(self.student["id"], self.teacher["id"], "Words")
        self.db.add_word(self.student["id"], "journey", "путешествие", None, None)
        word = self.db.list_words(self.student["id"])[0]

        self.assertTrue(self.db.add_word_to_lesson(lesson["id"], word["id"]))
        self.assertFalse(self.db.add_word_to_lesson(lesson["id"], word["id"]))

        rows = self.db.fetchall("SELECT * FROM lesson_words WHERE lesson_id = ?", (lesson["id"],))
        self.assertEqual(len(rows), 1)

    def test_add_homework_task_creates_task(self) -> None:
        lesson = self.db.create_lesson(self.student["id"], self.teacher["id"], "Homework")

        task = self.db.add_homework_task(
            lesson["id"],
            "translation",
            "Translate: journey",
            expected_answer="путешествие",
            metadata_json='{"source":"manual"}',
            order_index=2,
        )

        self.assertEqual(task["lesson_id"], lesson["id"])
        self.assertEqual(task["task_type"], "translation")
        self.assertEqual(task["prompt"], "Translate: journey")
        self.assertEqual(task["expected_answer"], "путешествие")
        self.assertEqual(task["metadata_json"], '{"source":"manual"}')
        self.assertEqual(task["order_index"], 2)
