from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date, timedelta
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

    def test_select_game_words_does_not_return_duplicates(self) -> None:
        for index in range(12):
            self.db.add_word(self.user["id"], f"word-{index}", f"слово-{index}", None, None)

        selected = self.db.select_game_words(self.user["id"], limit=10)

        self.assertEqual(len(selected), 10)
        self.assertEqual(len({word["id"] for word in selected}), 10)

    def test_daily_activity_updates_streak(self) -> None:
        today = date(2026, 6, 18)
        yesterday = today - timedelta(days=1)

        first = self.db.update_daily_activity(self.user["id"], yesterday, cards_reviewed=10)
        second = self.db.update_daily_activity(self.user["id"], today, cards_reviewed=10)
        second_again = self.db.update_daily_activity(self.user["id"], today, cards_reviewed=5)

        self.assertEqual(first["sessions_completed"], 1)
        self.assertEqual(second["sessions_completed"], 1)
        self.assertEqual(second_again["sessions_completed"], 2)
        self.assertEqual(second_again["cards_reviewed"], 15)
        self.assertTrue(self.db.has_completed_session_on(self.user["id"], today))
        self.assertEqual(self.db.current_streak(self.user["id"], today), 2)


if __name__ == "__main__":
    unittest.main()
