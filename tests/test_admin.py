from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from app.database import Database
from app.handlers.admin import _format_all_users
from app.handlers.start import require_user
from app.keyboards import ADD_STUDENT, ADMIN_MENU, ADMIN_STUDENT_VIEW, ADMIN_TEACHER_VIEW, ADMIN_USERS, ADMIN_MY_MENU, main_menu_keyboard, admin_menu_keyboard


@dataclass(frozen=True)
class AdminSettings:
    allowed_usernames: frozenset[str] = frozenset({"studentone"})
    admin_usernames: frozenset[str] = frozenset({"adminone"})
    teacher_usernames: frozenset[str] = frozenset({"teacherone"})


class AdminKeyboardTests(unittest.TestCase):
    def _texts(self, keyboard) -> list[str]:
        return [button.text for row in keyboard.keyboard for button in row]

    def test_admin_gets_student_menu_with_admin_button(self) -> None:
        texts = self._texts(main_menu_keyboard(include_admin=True))

        self.assertIn(ADMIN_MENU, texts)
        self.assertIn("📚 Мои уроки", texts)
        self.assertNotIn("🎯 Мои карточки", texts)

    def test_admin_menu_contains_minimal_admin_actions(self) -> None:
        texts = self._texts(admin_menu_keyboard())

        self.assertEqual(texts, [ADMIN_STUDENT_VIEW, ADMIN_TEACHER_VIEW, ADMIN_USERS, ADD_STUDENT, ADMIN_MY_MENU])


class AdminUsersReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.admin = self.db.upsert_user(1, "adminone", "Admin One")
        self.student = self.db.upsert_user(2, "studentone", "Student One")
        self.db.add_word(self.student["id"], "cat", "кот", None, None)
        self.context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": self.db, "settings": AdminSettings()}))

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_all_users_report_includes_role_words_and_streak(self) -> None:
        report = _format_all_users(self.context)

        self.assertIn("@adminone — Admin One | role: admin | words: 0 | streak: 0", report)
        self.assertIn("@studentone — Student One | role: student | words: 1 | streak: 0", report)


class AdminImpersonationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.admin = self.db.upsert_user(100, "adminone", "Admin One")
        self.student = self.db.upsert_user(200, "studentone", "Student One")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    async def test_admin_impersonation_returns_existing_student_without_duplicate_user(self) -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=100, username="adminone"), effective_message=None)
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"db": self.db, "settings": AdminSettings()}),
            user_data={"impersonated_user_id": self.student["id"]},
        )

        user = await require_user(update, context)

        self.assertEqual(user["id"], self.student["id"])
        self.assertEqual(self.db.get_user_by_telegram_id(100)["id"], self.admin["id"])
        self.assertEqual(len(self.db.list_users()), 2)


if __name__ == "__main__":
    unittest.main()
