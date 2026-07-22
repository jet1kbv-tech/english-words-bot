import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("backup_database", SCRIPTS_DIR / "backup_database.py")
backup_database = importlib.util.module_from_spec(_spec)
sys.modules["backup_database"] = backup_database
_spec.loader.exec_module(backup_database)


def _make_database(path: Path, rows: int = 1) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE words (id INTEGER PRIMARY KEY, english TEXT NOT NULL)")
    if rows == 1:
        connection.execute("INSERT INTO words (english) VALUES ('receipt')")
    else:
        connection.executemany(
            "INSERT INTO words (english) VALUES (?)",
            [(f"word-{i}",) for i in range(rows)],
        )
    connection.commit()
    connection.close()


def _corrupt_byte_range(path: Path, start: int, end: int) -> None:
    with open(path, "r+b") as handle:
        handle.seek(start)
        chunk = bytearray(handle.read(end - start))
        for i in range(len(chunk)):
            chunk[i] ^= 0xFF
        handle.seek(start)
        handle.write(chunk)


class BackupPathForTests(unittest.TestCase):
    def test_creates_backups_subdir_next_to_database(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "english_words_bot.sqlite3"
            db_path.touch()
            backup_path = backup_database.backup_path_for(db_path)
            self.assertEqual(backup_path.parent, db_path.parent / "backups")
            self.assertTrue(backup_path.parent.is_dir())
            self.assertTrue(backup_path.name.startswith("english_words_bot.sqlite3.pre-deploy-"))


class CreateAndVerifyBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "source.sqlite3"
        _make_database(self.db_path)
        self.backup_path = Path(self.tmp.name) / "backup.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_backup_contains_same_data_and_passes_integrity_check(self) -> None:
        backup_database.create_backup(self.db_path, self.backup_path)

        connection = sqlite3.connect(self.backup_path)
        rows = connection.execute("SELECT english FROM words").fetchall()
        connection.close()
        self.assertEqual(rows, [("receipt",)])
        self.assertEqual(backup_database.verify_integrity(self.backup_path), "ok")

    def test_backup_of_truncated_source_raises(self) -> None:
        # Truncating to fewer bytes than SQLite's 100-byte header is what
        # reliably makes source.backup() itself raise ("file is not a
        # database"), confirmed empirically across repeated runs. Truncating
        # to a size that still contains a full header (e.g. 50 bytes) instead
        # lets backup() succeed structurally, with corruption only surfacing
        # later via PRAGMA integrity_check - see
        # test_backup_of_page_corrupted_source_fails_integrity_check below.
        corrupt_path = Path(self.tmp.name) / "corrupt.sqlite3"
        with open(self.db_path, "rb") as source, open(corrupt_path, "wb") as dest:
            dest.write(source.read(10))

        with self.assertRaises(sqlite3.Error):
            backup_database.create_backup(corrupt_path, self.backup_path)

    def test_backup_of_page_corrupted_source_fails_integrity_check(self) -> None:
        corrupt_path = Path(self.tmp.name) / "corrupt.sqlite3"
        _make_database(corrupt_path, rows=200)
        _corrupt_byte_range(corrupt_path, 4200, 4400)

        backup_database.create_backup(corrupt_path, self.backup_path)

        self.assertNotEqual(backup_database.verify_integrity(self.backup_path), "ok")


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_main_with_db_path(self, db_path: Path) -> int:
        with patch.object(backup_database, "database_path", return_value=db_path):
            return backup_database.main()

    def test_missing_database_returns_error(self) -> None:
        missing = Path(self.tmp.name) / "does-not-exist.sqlite3"
        self.assertEqual(self._run_main_with_db_path(missing), 1)

    def test_successful_backup_returns_zero_and_creates_verified_file(self) -> None:
        db_path = Path(self.tmp.name) / "english_words_bot.sqlite3"
        _make_database(db_path)

        exit_code = self._run_main_with_db_path(db_path)

        self.assertEqual(exit_code, 0)
        backups = list((db_path.parent / "backups").glob("*.pre-deploy-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backup_database.verify_integrity(backups[0]), "ok")

    def test_corrupted_database_returns_error_and_does_not_crash(self) -> None:
        db_path = Path(self.tmp.name) / "corrupt.sqlite3"
        good_path = Path(self.tmp.name) / "good.sqlite3"
        _make_database(good_path)
        with open(good_path, "rb") as source, open(db_path, "wb") as dest:
            dest.write(source.read(50))

        exit_code = self._run_main_with_db_path(db_path)

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
