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


    def test_create_teacher_lesson_creates_draft_lesson(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])

        self.assertEqual(lesson["title"], "Lesson 15 — Food")
        self.assertEqual(lesson["teacher_user_id"], self.teacher["id"])
        self.assertIsNone(lesson["student_user_id"])
        self.assertEqual(lesson["status"], "DRAFT")
        self.assertEqual(lesson["lesson_number"], 15)
        self.assertEqual(lesson["topic"], "Food")
        self.assertIsNone(lesson["description"])
        self.assertIsNone(lesson["level"])

    def test_lesson_metadata_columns_are_idempotently_added(self) -> None:
        self.db.execute("ALTER TABLE lessons RENAME TO lessons_new")
        self.db.execute("""
            CREATE TABLE lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_user_id INTEGER,
                student_user_id INTEGER,
                title TEXT NOT NULL,
                theme TEXT,
                grammar_topic TEXT,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.db.execute("""
            INSERT INTO lessons (teacher_user_id, student_user_id, title, status, created_at, updated_at)
            VALUES (?, NULL, 'Legacy', 'draft', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
        """, (self.teacher["id"],))
        self.db.execute("DROP TABLE lessons_new")

        self.db.init_schema()
        self.db.init_schema()

        columns = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lessons)")}
        self.assertIn("lesson_number", columns)
        self.assertIn("topic", columns)
        self.assertIn("description", columns)
        self.assertIn("level", columns)
        legacy = self.db.list_lessons()[0]
        self.assertEqual(legacy["title"], "Legacy")
        self.assertEqual(legacy["status"], "DRAFT")
        self.assertIsNone(legacy["topic"])

    def test_teacher_lesson_metadata_parser_variants(self) -> None:
        travel = self.db.create_teacher_lesson("15 - Travel", self.teacher["id"])
        food = self.db.create_teacher_lesson("Food", self.teacher["id"])

        self.assertEqual(travel["title"], "15 - Travel")
        self.assertEqual(travel["lesson_number"], 15)
        self.assertEqual(travel["topic"], "Travel")
        self.assertEqual(food["title"], "Food")
        self.assertIsNone(food["lesson_number"])
        self.assertEqual(food["topic"], "Food")

    def test_list_lessons_returns_created_lessons(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 16 — Travel", self.teacher["id"])

        lessons = self.db.list_lessons()

        self.assertEqual([row["id"] for row in lessons], [lesson["id"]])

    def test_get_lesson_summary_returns_counts(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 17 — Food", self.teacher["id"])
        self.db.add_word(self.student["id"], "apple", "яблоко", None, None)
        word = self.db.list_words(self.student["id"])[0]
        self.db.add_word_to_lesson(lesson["id"], word["id"])
        self.db.add_homework_task(lesson["id"], "text", "Write a sentence")

        summary = self.db.get_lesson_summary(lesson["id"])

        self.assertEqual(summary["words_count"], 1)
        self.assertEqual(summary["homework_tasks_count"], 1)
        self.assertEqual(summary["homework_count"], 1)
        self.assertEqual(summary["grammar_count"], 0)
        self.assertEqual(summary["exercises_count"], 0)

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
        self.assertEqual(lesson["status"], "DRAFT")

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


    def test_add_lesson_words_imports_single_word(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 18 — Food", self.teacher["id"])

        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])

        words = self.db.list_lesson_words(lesson["id"])
        self.assertEqual([word["text"] for word in words], ["receipt"])

    def test_add_lesson_words_keeps_order(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 19 — Food", self.teacher["id"])

        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it", "stale"], self.teacher["id"])

        words = self.db.list_lesson_words(lesson["id"])
        self.assertEqual([word["text"] for word in words], ["receipt", "worth it", "stale"])

    def test_update_lesson_word_fields_and_clear_value(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 20 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word_id = self.db.list_lesson_words(lesson["id"])[0]["word_id"]

        self.assertTrue(self.db.update_word_translation(lesson["id"], word_id, "чек"))
        self.assertTrue(self.db.update_word_example(lesson["id"], word_id, "Can I have the receipt, please?"))
        self.assertTrue(self.db.update_word_topic(lesson["id"], word_id, "Shopping"))

        word = self.db.get_lesson_word(lesson["id"], word_id)
        self.assertEqual(word["translation"], "чек")
        self.assertEqual(word["example"], "Can I have the receipt, please?")
        self.assertEqual(word["topic"], "Shopping")

        self.assertTrue(self.db.update_word_topic(lesson["id"], word_id, None))
        self.assertIsNone(self.db.get_lesson_word(lesson["id"], word_id)["topic"])

    def test_get_lesson_word_requires_matching_lesson_relation(self) -> None:
        food = self.db.create_teacher_lesson("Lesson 20 — Food", self.teacher["id"])
        travel = self.db.create_teacher_lesson("Lesson 21 — Travel", self.teacher["id"])
        self.db.add_lesson_words(food["id"], ["receipt"], self.teacher["id"])
        word_id = self.db.list_lesson_words(food["id"])[0]["word_id"]

        word = self.db.get_lesson_word(food["id"], word_id)

        self.assertIsNotNone(word)
        self.assertEqual(word["english"], "receipt")
        self.assertIsNone(self.db.get_lesson_word(travel["id"], word_id))

    def test_list_lesson_training_words_includes_student_progress(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 20 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it"], self.teacher["id"])
        word_ids = [row["word_id"] for row in self.db.list_lesson_words(lesson["id"])]
        # Student builds progress on the first (teacher-owned) lesson word.
        self.db.update_progress(self.student["id"], word_ids[0], remembered=True)

        rows = self.db.list_lesson_training_words(lesson["id"], self.student["id"])

        self.assertEqual([row["english"] for row in rows], ["receipt", "worth it"])
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id[word_ids[0]]["progress_score"], 1)
        self.assertEqual(by_id[word_ids[0]]["times_remembered"], 1)
        # A word the student has not practised has no progress row yet.
        self.assertIsNone(by_id[word_ids[1]]["progress_score"])
        # Another lesson's words are not included.
        other = self.db.create_teacher_lesson("Lesson 21 — Travel", self.teacher["id"])
        self.assertEqual(self.db.list_lesson_training_words(other["id"], self.student["id"]), [])

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

    def test_list_homework_tasks_orders_by_order_index(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 22 — Food", self.teacher["id"])
        self.db.add_homework_task(lesson["id"], "free", "Second", order_index=1)
        self.db.add_homework_task(lesson["id"], "free", "First", order_index=0)

        other = self.db.create_teacher_lesson("Lesson 23 — Travel", self.teacher["id"])
        self.db.add_homework_task(other["id"], "free", "Other lesson task")

        tasks = self.db.list_homework_tasks(lesson["id"])

        self.assertEqual([task["prompt"] for task in tasks], ["First", "Second"])

    def test_get_homework_task_requires_matching_lesson(self) -> None:
        food = self.db.create_teacher_lesson("Lesson 24 — Food", self.teacher["id"])
        travel = self.db.create_teacher_lesson("Lesson 25 — Travel", self.teacher["id"])
        task = self.db.add_homework_task(food["id"], "free", "Write something")

        self.assertIsNotNone(self.db.get_homework_task(food["id"], task["id"]))
        self.assertIsNone(self.db.get_homework_task(travel["id"], task["id"]))

    def test_delete_homework_task_removes_task_and_answers(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 26 — Food", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "free", "Write something")
        self.db.execute(
            "INSERT INTO homework_answers (task_id, user_id, answer, created_at) VALUES (?, ?, ?, ?)",
            (task["id"], self.student["id"], "my answer", "2026-01-01T00:00:00"),
        )

        deleted = self.db.delete_homework_task(lesson["id"], task["id"])

        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_homework_task(lesson["id"], task["id"]))
        self.assertEqual(self.db.fetchall("SELECT * FROM homework_answers WHERE task_id = ?", (task["id"],)), [])

    def test_delete_homework_task_returns_false_for_wrong_lesson(self) -> None:
        food = self.db.create_teacher_lesson("Lesson 27 — Food", self.teacher["id"])
        travel = self.db.create_teacher_lesson("Lesson 28 — Travel", self.teacher["id"])
        task = self.db.add_homework_task(food["id"], "free", "Write something")

        self.assertFalse(self.db.delete_homework_task(travel["id"], task["id"]))
        self.assertIsNotNone(self.db.get_homework_task(food["id"], task["id"]))

    def test_submit_homework_answer_records_row(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 29 — Food", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "translation", "receipt", "чек")

        answer = self.db.submit_homework_answer(task["id"], self.student["id"], "чек", is_correct=True, feedback="Отлично")

        self.assertEqual(answer["task_id"], task["id"])
        self.assertEqual(answer["user_id"], self.student["id"])
        self.assertEqual(answer["answer"], "чек")
        self.assertEqual(answer["is_correct"], 1)
        self.assertEqual(answer["feedback"], "Отлично")

    def test_submit_homework_answer_allows_pending_review_with_null_is_correct(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 30 — Food", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "free", "Write something")

        answer = self.db.submit_homework_answer(task["id"], self.student["id"], "my answer")

        self.assertIsNone(answer["is_correct"])
        self.assertIsNone(answer["feedback"])

    def test_list_latest_homework_answers_keeps_only_newest_per_task(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 31 — Food", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "translation", "receipt", "чек")
        other_task = self.db.add_homework_task(lesson["id"], "free", "Write something")
        other_lesson = self.db.create_teacher_lesson("Lesson 32 — Travel", self.teacher["id"])
        other_lesson_task = self.db.add_homework_task(other_lesson["id"], "free", "Different lesson")

        self.db.submit_homework_answer(task["id"], self.student["id"], "wrong", is_correct=False)
        self.db.submit_homework_answer(task["id"], self.student["id"], "чек", is_correct=True)
        self.db.submit_homework_answer(other_lesson_task["id"], self.student["id"], "irrelevant")

        answers = self.db.list_latest_homework_answers(lesson["id"], self.student["id"])

        self.assertEqual(set(answers.keys()), {task["id"]})
        self.assertEqual(answers[task["id"]]["answer"], "чек")
        self.assertEqual(answers[task["id"]]["is_correct"], 1)
        self.assertNotIn(other_task["id"], answers)


class LessonGrammarExercisesDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.student = self.db.upsert_user(40, "student", "Student")
        self.teacher = self.db.upsert_user(41, "teacher", "Teacher")
        self.lesson = self.db.create_teacher_lesson("Lesson 40 — Food", self.teacher["id"])

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def _assignment_id(self) -> int:
        self.db.assign_lesson_to_student(self.lesson["id"], "student", self.teacher["id"])
        return int(self.db.get_active_lesson_assignment(self.lesson["id"])["id"])

    def test_add_and_list_grammar_items_orders_by_position(self) -> None:
        self.db.add_grammar_item(self.lesson["id"], "Second", "Explanation 2", position=1)
        self.db.add_grammar_item(self.lesson["id"], "First", "Explanation 1", position=0)

        items = self.db.list_grammar_items(self.lesson["id"])

        self.assertEqual([item["title"] for item in items], ["First", "Second"])
        self.assertEqual(items[0]["explanation"], "Explanation 1")
        self.assertIsNone(items[0]["example"])

    def test_get_grammar_item_requires_matching_lesson(self) -> None:
        other = self.db.create_teacher_lesson("Lesson 41 — Travel", self.teacher["id"])
        item = self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")

        self.assertIsNotNone(self.db.get_grammar_item(self.lesson["id"], item["id"]))
        self.assertIsNone(self.db.get_grammar_item(other["id"], item["id"]))

    def test_delete_grammar_item(self) -> None:
        item = self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")

        self.assertTrue(self.db.delete_grammar_item(self.lesson["id"], item["id"]))
        self.assertIsNone(self.db.get_grammar_item(self.lesson["id"], item["id"]))
        self.assertFalse(self.db.delete_grammar_item(self.lesson["id"], item["id"]))

    def test_delete_grammar_item_removes_progress(self) -> None:
        assignment_id = self._assignment_id()
        item = self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")
        self.db.mark_grammar_item_completed(assignment_id, item["id"])

        self.db.delete_grammar_item(self.lesson["id"], item["id"])

        self.assertEqual(self.db.fetchall("SELECT * FROM student_grammar_progress WHERE grammar_item_id = ?", (item["id"],)), [])

    def test_mark_grammar_item_completed_is_idempotent(self) -> None:
        assignment_id = self._assignment_id()
        item = self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")

        first = self.db.mark_grammar_item_completed(assignment_id, item["id"])
        second = self.db.mark_grammar_item_completed(assignment_id, item["id"])

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["completed_at"], second["completed_at"])
        rows = self.db.fetchall(
            "SELECT * FROM student_grammar_progress WHERE assignment_id = ? AND grammar_item_id = ?",
            (assignment_id, item["id"]),
        )
        self.assertEqual(len(rows), 1)

    def test_list_grammar_progress_is_scoped_to_assignment(self) -> None:
        item = self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")
        first_assignment_id = self._assignment_id()
        self.db.mark_grammar_item_completed(first_assignment_id, item["id"])

        self.db.unassign_lesson(self.lesson["id"])
        second_assignment_id = self._assignment_id()

        self.assertNotEqual(first_assignment_id, second_assignment_id)
        self.assertEqual(set(self.db.list_grammar_progress(first_assignment_id).keys()), {item["id"]})
        self.assertEqual(self.db.list_grammar_progress(second_assignment_id), {})

    def test_add_and_list_exercise_items_orders_by_position(self) -> None:
        self.db.add_exercise_item(self.lesson["id"], "Second prompt", '["a", "b"]', 0, position=1)
        self.db.add_exercise_item(self.lesson["id"], "First prompt", '["a", "b"]', 0, position=0)

        items = self.db.list_exercise_items(self.lesson["id"])

        self.assertEqual([item["prompt"] for item in items], ["First prompt", "Second prompt"])

    def test_add_exercise_item_stores_options_and_correct_index(self) -> None:
        item = self.db.add_exercise_item(self.lesson["id"], "I ___ every day.", '["work", "works"]', 0, "Base form with I.")

        self.assertEqual(item["prompt"], "I ___ every day.")
        self.assertEqual(item["options_json"], '["work", "works"]')
        self.assertEqual(item["correct_option_index"], 0)
        self.assertEqual(item["explanation"], "Base form with I.")

    def test_delete_exercise_item_removes_item_and_answers(self) -> None:
        assignment_id = self._assignment_id()
        item = self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)
        self.db.submit_exercise_answer(assignment_id, item["id"], self.student["id"], 0, True)

        deleted = self.db.delete_exercise_item(self.lesson["id"], item["id"])

        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_exercise_item(self.lesson["id"], item["id"]))
        self.assertEqual(self.db.fetchall("SELECT * FROM lesson_exercise_answers WHERE exercise_id = ?", (item["id"],)), [])

    def test_submit_exercise_answer_records_row(self) -> None:
        assignment_id = self._assignment_id()
        item = self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)

        answer = self.db.submit_exercise_answer(assignment_id, item["id"], self.student["id"], 0, True)

        self.assertEqual(answer["assignment_id"], assignment_id)
        self.assertEqual(answer["exercise_id"], item["id"])
        self.assertEqual(answer["user_id"], self.student["id"])
        self.assertEqual(answer["selected_option_index"], 0)
        self.assertEqual(answer["is_correct"], 1)

    def test_submit_exercise_answer_keeps_first_attempt(self) -> None:
        assignment_id = self._assignment_id()
        item = self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)

        first = self.db.submit_exercise_answer(assignment_id, item["id"], self.student["id"], 0, True)
        second = self.db.submit_exercise_answer(assignment_id, item["id"], self.student["id"], 1, False)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["selected_option_index"], 0)
        self.assertEqual(second["is_correct"], 1)

    def test_list_exercise_answers_is_scoped_to_assignment(self) -> None:
        item = self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)
        first_assignment_id = self._assignment_id()
        self.db.submit_exercise_answer(first_assignment_id, item["id"], self.student["id"], 0, True)

        self.db.unassign_lesson(self.lesson["id"])
        second_assignment_id = self._assignment_id()

        self.assertNotEqual(first_assignment_id, second_assignment_id)
        self.assertEqual(set(self.db.list_exercise_answers(first_assignment_id).keys()), {item["id"]})
        self.assertEqual(self.db.list_exercise_answers(second_assignment_id), {})

    def test_get_exercise_item_requires_matching_lesson(self) -> None:
        other_lesson = self.db.create_teacher_lesson("Lesson 42 — Travel", self.teacher["id"])
        other_item = self.db.add_exercise_item(other_lesson["id"], "Different lesson", '["x", "y"]', 0)

        self.assertIsNone(self.db.get_exercise_item(self.lesson["id"], other_item["id"]))
        self.assertIsNotNone(self.db.get_exercise_item(other_lesson["id"], other_item["id"]))

    def test_get_lesson_summary_reflects_real_grammar_and_exercise_counts(self) -> None:
        self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")
        self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)

        summary = self.db.get_lesson_summary(self.lesson["id"])

        self.assertEqual(summary["grammar_count"], 1)
        self.assertEqual(summary["exercises_count"], 1)

    def test_get_student_lesson_reflects_real_completed_counts(self) -> None:
        assignment_id = self._assignment_id()
        grammar_item = self.db.add_grammar_item(self.lesson["id"], "Title", "Explanation")
        self.db.add_grammar_item(self.lesson["id"], "Title2", "Explanation2")
        exercise_item = self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)

        summary_before = self.db.get_student_lesson(self.lesson["id"], "student")
        self.assertEqual(summary_before["grammar_completed_count"], 0)
        self.assertEqual(summary_before["exercises_completed_count"], 0)
        self.assertEqual(summary_before["assignment_id"], assignment_id)

        self.db.mark_grammar_item_completed(assignment_id, grammar_item["id"])
        self.db.submit_exercise_answer(assignment_id, exercise_item["id"], self.student["id"], 0, True)

        summary_after = self.db.get_student_lesson(self.lesson["id"], "student")
        self.assertEqual(summary_after["grammar_completed_count"], 1)
        self.assertEqual(summary_after["exercises_completed_count"], 1)

    def test_set_student_lesson_section_persists_and_finishes(self) -> None:
        self.db.assign_lesson_to_student(self.lesson["id"], "student", self.teacher["id"])

        self.db.set_student_lesson_section(self.lesson["id"], "student", "GRAMMAR")
        summary = self.db.get_student_lesson(self.lesson["id"], "student")
        self.assertEqual(summary["current_section"], "GRAMMAR")

        self.db.set_student_lesson_section(self.lesson["id"], "student", "FINISHED")
        row = self.db.fetchone("SELECT * FROM lesson_students WHERE lesson_id = ? AND student_username = ?", (self.lesson["id"], "student"))
        self.assertEqual(row["current_section"], "FINISHED")
        self.assertIsNotNone(row["completed_at"])

    def test_current_section_column_is_idempotently_added(self) -> None:
        self.db.execute("ALTER TABLE lesson_students DROP COLUMN current_section")
        columns_before = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lesson_students)")}
        self.assertNotIn("current_section", columns_before)

        self.db.init_schema()
        self.db.init_schema()

        columns_after = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lesson_students)")}
        self.assertIn("current_section", columns_after)

    def test_exercise_tables_are_rebuilt_from_old_free_text_schema(self) -> None:
        self.db.execute(
            """
            CREATE TABLE lesson_exercise_items_old (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                prompt TEXT NOT NULL,
                expected_answer TEXT NOT NULL,
                hint TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.db.execute("DROP TABLE lesson_exercise_items")
        self.db.execute("ALTER TABLE lesson_exercise_items_old RENAME TO lesson_exercise_items")
        columns_before = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lesson_exercise_items)")}
        self.assertIn("expected_answer", columns_before)

        self.db.init_schema()
        self.db.init_schema()

        columns_after = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lesson_exercise_items)")}
        self.assertNotIn("expected_answer", columns_after)
        self.assertIn("options_json", columns_after)
        self.assertIn("correct_option_index", columns_after)
        answer_columns = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lesson_exercise_answers)")}
        self.assertIn("assignment_id", answer_columns)
        # New schema still works after the rebuild.
        item = self.db.add_exercise_item(self.lesson["id"], "Prompt", '["a", "b"]', 0)
        self.assertEqual(self.db.list_exercise_items(self.lesson["id"]), [item])


class TeacherLessonListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.student = self.db.upsert_user(30, "student", "Student")
        self.teacher = self.db.upsert_user(31, "teacher", "Teacher")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_list_lessons_for_teacher_includes_student_and_limit(self) -> None:
        for index in range(12):
            self.db.create_lesson(self.student["id"], self.teacher["id"], f"Lesson {index}", theme="Theme")

        lessons = self.db.list_lessons_for_teacher(self.teacher["id"], limit=10)

        self.assertEqual(len(lessons), 10)
        self.assertEqual(lessons[0]["title"], "Lesson 11")
        self.assertEqual(lessons[0]["student_display_name"], "Student")
        self.assertEqual(lessons[0]["student_username"], "student")
        self.assertEqual(lessons[0]["status"], "DRAFT")

class StudentAccessDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_add_student_access_normalizes_and_reactivates(self) -> None:
        row = self.db.add_student_access(" @NewStudent ")
        self.assertEqual(row["username"], "newstudent")
        self.db.execute("UPDATE student_access SET is_active = 0 WHERE username = ?", ("newstudent",))

        updated = self.db.add_student_access("NEWSTUDENT")

        self.assertEqual(updated["username"], "newstudent")
        self.assertEqual(updated["is_active"], 1)

    def test_inactive_student_access_is_not_active(self) -> None:
        self.db.add_student_access("newstudent")
        self.db.execute("UPDATE student_access SET is_active = 0 WHERE username = ?", ("newstudent",))

        self.assertFalse(self.db.is_active_student_access("newstudent"))

class StudentAccessAdditionalDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_student_access_normalizes_username(self) -> None:
        row = self.db.add_student_access("@PrivetNormalno")

        self.assertEqual(row["username"], "privetnormalno")

    def test_duplicate_active_student_access_is_single_active_row(self) -> None:
        self.db.add_student_access("studentone")
        self.db.add_student_access("@StudentOne")

        rows = self.db.fetchall("SELECT * FROM student_access WHERE username = ?", ("studentone",))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["is_active"], 1)

    def test_inactive_student_access_reactivation(self) -> None:
        self.db.add_student_access("studentone")
        self.db.execute("UPDATE student_access SET is_active = 0 WHERE username = ?", ("studentone",))

        row = self.db.add_student_access("studentone")

        self.assertEqual(row["is_active"], 1)

class LessonAssignmentDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(10, "romateaches", "Roma")
        self.lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_create_assignment(self) -> None:
        assignment = self.db.assign_lesson_to_student(self.lesson["id"], "@PrivetNormalno", self.teacher["id"])
        self.assertEqual(assignment["student_username"], "privetnormalno")
        self.assertEqual(assignment["status"], "ASSIGNED")
        self.assertEqual(assignment["is_active"], 1)

    def test_reassign_creates_history_and_only_one_active(self) -> None:
        self.db.assign_lesson_to_student(self.lesson["id"], "privetnormalno", self.teacher["id"])
        self.db.assign_lesson_to_student(self.lesson["id"], "wp_bvv", self.teacher["id"])
        history = self.db.list_lesson_assignment_history(self.lesson["id"])
        self.assertEqual([row["student_username"] for row in history], ["privetnormalno", "wp_bvv"])
        self.assertEqual(sum(int(row["is_active"]) for row in history), 1)
        self.assertEqual(self.db.get_active_lesson_assignment(self.lesson["id"])["student_username"], "wp_bvv")

    def test_assign_same_student_does_not_duplicate_active_assignment(self) -> None:
        first = self.db.assign_lesson_to_student(self.lesson["id"], "privetnormalno", self.teacher["id"])
        second = self.db.assign_lesson_to_student(self.lesson["id"], "@privetnormalno", self.teacher["id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.db.list_lesson_assignment_history(self.lesson["id"])), 1)

    def test_unassign_preserves_history_and_clears_active_assignment(self) -> None:
        self.db.assign_lesson_to_student(self.lesson["id"], "privetnormalno", self.teacher["id"])
        self.db.unassign_lesson(self.lesson["id"])
        self.assertIsNone(self.db.get_active_lesson_assignment(self.lesson["id"]))
        history = self.db.list_lesson_assignment_history(self.lesson["id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["is_active"], 0)
        self.assertIsNotNone(history[0]["unassigned_at"])

    def test_missing_lesson_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.db.assign_lesson_to_student(999, "privetnormalno", self.teacher["id"])

    def test_no_student_username_or_student_id_added_to_lessons_table(self) -> None:
        columns = {row["name"] for row in self.db.fetchall("PRAGMA table_info(lessons)")}
        self.assertNotIn("student_username", columns)
        self.assertNotIn("student_id", columns)


class LessonServiceHomeworkTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.lesson_repository import LessonRepository
        from app.lesson_service import LessonService

        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(40, "teacher", "Teacher")
        self.student = self.db.upsert_user(41, "student", "Student")
        self.lesson = self.db.create_teacher_lesson("Lesson 50 — Food", self.teacher["id"])
        self.service = LessonService(LessonRepository(self.db))

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_add_translation_task_trims_and_orders(self) -> None:
        from app.lesson_service import HOMEWORK_TASK_TYPE_TRANSLATION

        first = self.service.add_translation_task(self.lesson["id"], "  receipt  ", "  чек  ")
        second = self.service.add_translation_task(self.lesson["id"], "worth it")

        self.assertEqual(first["task_type"], HOMEWORK_TASK_TYPE_TRANSLATION)
        self.assertEqual(first["prompt"], "receipt")
        self.assertEqual(first["expected_answer"], "чек")
        self.assertEqual(first["order_index"], 0)
        self.assertEqual(second["order_index"], 1)
        self.assertIsNone(second["expected_answer"])

    def test_add_translation_task_rejects_empty_prompt(self) -> None:
        from app.lesson_service import HomeworkTaskError

        with self.assertRaises(HomeworkTaskError):
            self.service.add_translation_task(self.lesson["id"], "   ")

    def test_add_translation_task_rejects_too_long_prompt(self) -> None:
        from app.lesson_service import HomeworkTaskError, MAX_HOMEWORK_PROMPT_LENGTH

        with self.assertRaises(HomeworkTaskError):
            self.service.add_translation_task(self.lesson["id"], "x" * (MAX_HOMEWORK_PROMPT_LENGTH + 1))

    def test_add_free_task_stores_prompt_only(self) -> None:
        from app.lesson_service import HOMEWORK_TASK_TYPE_FREE

        task = self.service.add_free_task(self.lesson["id"], "Write two sentences")

        self.assertEqual(task["task_type"], HOMEWORK_TASK_TYPE_FREE)
        self.assertIsNone(task["expected_answer"])
        self.assertIsNone(task["metadata_json"])

    def test_add_quiz_task_stores_options_and_correct_index(self) -> None:
        import json
        from app.lesson_service import HOMEWORK_TASK_TYPE_QUIZ

        task = self.service.add_quiz_task(self.lesson["id"], "Pick one", ["receipt", "recipe", ""], correct_index=0)

        self.assertEqual(task["task_type"], HOMEWORK_TASK_TYPE_QUIZ)
        self.assertEqual(task["expected_answer"], "receipt")
        metadata = json.loads(task["metadata_json"])
        # Blank lines are dropped before validating/storing options.
        self.assertEqual(metadata["options"], ["receipt", "recipe"])
        self.assertEqual(metadata["correct_index"], 0)

    def test_add_quiz_task_rejects_too_few_options(self) -> None:
        from app.lesson_service import HomeworkTaskError

        with self.assertRaises(HomeworkTaskError):
            self.service.add_quiz_task(self.lesson["id"], "Pick one", ["only"], correct_index=0)

    def test_add_quiz_task_rejects_too_many_options(self) -> None:
        from app.lesson_service import HomeworkTaskError, MAX_QUIZ_OPTIONS

        with self.assertRaises(HomeworkTaskError):
            self.service.add_quiz_task(self.lesson["id"], "Pick one", [f"opt{i}" for i in range(MAX_QUIZ_OPTIONS + 1)], correct_index=0)

    def test_add_quiz_task_rejects_out_of_range_correct_index(self) -> None:
        from app.lesson_service import HomeworkTaskError

        with self.assertRaises(HomeworkTaskError):
            self.service.add_quiz_task(self.lesson["id"], "Pick one", ["a", "b"], correct_index=5)

    def test_submit_homework_answer_validates_task_and_length(self) -> None:
        from app.lesson_service import HomeworkTaskError, MAX_HOMEWORK_ANSWER_LENGTH

        task = self.service.add_free_task(self.lesson["id"], "Write something")

        answer = self.service.submit_homework_answer(self.lesson["id"], task["id"], self.student["id"], "  my answer  ")
        self.assertEqual(answer["answer"], "my answer")

        with self.assertRaises(HomeworkTaskError):
            self.service.submit_homework_answer(self.lesson["id"], task["id"], self.student["id"], "   ")
        with self.assertRaises(HomeworkTaskError):
            self.service.submit_homework_answer(self.lesson["id"], task["id"], self.student["id"], "x" * (MAX_HOMEWORK_ANSWER_LENGTH + 1))

    def test_submit_homework_answer_rejects_wrong_lesson(self) -> None:
        other_lesson = self.db.create_teacher_lesson("Lesson 51 — Travel", self.teacher["id"])
        task = self.service.add_free_task(self.lesson["id"], "Write something")

        with self.assertRaises(ValueError):
            self.service.submit_homework_answer(other_lesson["id"], task["id"], self.student["id"], "answer")
