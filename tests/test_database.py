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
        self.assertEqual(activity["day_level"], "Разогрев")

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
