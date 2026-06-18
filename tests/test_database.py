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
