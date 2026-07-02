from dataclasses import dataclass
import unittest

from app.auth.roles import Role, RoleResolver, get_user_role, is_user_allowed
from app.handlers.teacher import _format_created_lesson, _format_teacher_lessons, _format_student_progress, _student_users, handle_teacher_message, NOT_STARTED_TEXT
from app.keyboards import ADD_STUDENT, TEACHER_CREATE_LESSON, TEACHER_LESSONS, TEACHER_MY_LESSONS, teacher_lessons_keyboard, teacher_menu_keyboard


@dataclass(frozen=True)
class RoleSettings:
    allowed_usernames: frozenset[str] = frozenset({"privetnormalno"})
    admin_usernames: frozenset[str] = frozenset({"wp_bvv"})
    teacher_usernames: frozenset[str] = frozenset({"romateaches"})


class RoleResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = RoleSettings()

    def test_wp_bvv_is_admin(self) -> None:
        self.assertEqual(get_user_role("wp_bvv", self.settings), Role.ADMIN)

    def test_romateaches_is_teacher(self) -> None:
        self.assertEqual(get_user_role("romateaches", self.settings), Role.TEACHER)

    def test_privetnormalno_is_student(self) -> None:
        self.assertEqual(get_user_role("privetnormalno", self.settings), Role.STUDENT)

    def test_role_resolution_is_case_insensitive(self) -> None:
        self.assertEqual(get_user_role("@WP_BVV", self.settings), Role.ADMIN)
        self.assertTrue(is_user_allowed("ROMATEACHES", self.settings))
        self.assertTrue(is_user_allowed("PrivetNormalno", self.settings))

    def test_none_username_does_not_crash(self) -> None:
        self.assertEqual(get_user_role(None, self.settings), Role.STUDENT)
        self.assertFalse(is_user_allowed(None, self.settings))

    def test_resolver_exposes_only_student_allowed_usernames(self) -> None:
        resolver = RoleResolver(self.settings)
        self.assertEqual(resolver.student_usernames, {"privetnormalno"})


class TeacherLessonUiTests(unittest.TestCase):
    def _texts(self, keyboard) -> list[str]:
        return [button.text for row in keyboard.keyboard for button in row]

    def test_teacher_menu_has_lessons_button(self) -> None:
        self.assertIn(TEACHER_LESSONS, self._texts(teacher_menu_keyboard()))

    def test_teacher_lessons_menu_has_create_and_my_lessons(self) -> None:
        self.assertEqual(self._texts(teacher_lessons_keyboard())[:2], [TEACHER_CREATE_LESSON, TEACHER_MY_LESSONS])

    def test_lesson_formatters_show_requested_fields(self) -> None:
        lesson = {"title": "Past Simple", "theme": None, "grammar_topic": "Past Simple", "status": "draft"}
        student = {"display_name": "Student", "username": "student"}

        created = _format_created_lesson(lesson, student)

        self.assertIn("Урок создан", created)
        self.assertIn("title: Past Simple", created)
        self.assertIn("student: Student (@student)", created)
        self.assertIn("theme: -", created)
        self.assertIn("grammar_topic: Past Simple", created)
        self.assertIn("status=draft", created)

    def test_my_lessons_formatter_shows_title_student_theme_status(self) -> None:
        lesson = {
            "title": "Past Simple",
            "student_display_name": "Student",
            "student_username": "student",
            "theme": "Travel",
            "status": "draft",
        }

        formatted = _format_teacher_lessons([lesson])

        self.assertIn("Past Simple", formatted)
        self.assertIn("Student (@student)", formatted)
        self.assertIn("theme: Travel", formatted)
        self.assertIn("status: draft", formatted)


if __name__ == "__main__":
    unittest.main()

class StudentAccessRoleTests(unittest.TestCase):
    def setUp(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from app.database import Database

        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.settings = RoleSettings()

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_student_access_allows_user_as_student(self) -> None:
        self.db.add_student_access("newstudent")
        resolver = RoleResolver(self.settings, self.db)

        self.assertTrue(resolver.is_allowed("newstudent"))
        self.assertEqual(resolver.role_for("newstudent"), Role.STUDENT)

    def test_inactive_student_access_does_not_allow_user(self) -> None:
        self.db.add_student_access("newstudent")
        self.db.execute("UPDATE student_access SET is_active = 0 WHERE username = ?", ("newstudent",))

        self.assertFalse(RoleResolver(self.settings, self.db).is_allowed("newstudent"))

class TeacherStudentAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from app.database import Database

        self.SimpleNamespace = SimpleNamespace
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(101, "romateaches", "Roma")
        self.admin = self.db.upsert_user(102, "wp_bvv", "Вова")
        self.context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": self.db, "settings": RoleSettings()}), user_data={})

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def _update(self, text: str):
        message = self.SimpleNamespace(text=text, replies=[])
        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))
        message.reply_text = reply_text
        return self.SimpleNamespace(effective_user=self.SimpleNamespace(id=101, username="romateaches"), effective_message=message)

    async def test_teacher_can_add_student(self) -> None:
        first = self._update(ADD_STUDENT)
        self.assertTrue(await handle_teacher_message(first, self.context))
        second = self._update(" @NewStudent ")
        self.assertTrue(await handle_teacher_message(second, self.context))

        self.assertTrue(self.db.is_active_student_access("newstudent"))
        self.assertEqual(second.effective_message.replies[-1][0], "Ученик @newstudent добавлен ✅\n\nЕсли он ещё не запускал бота, попросите его открыть бота и нажать /start.")


    async def test_teacher_duplicate_active_student_message(self) -> None:
        self.db.add_student_access("newstudent")
        self.context.user_data["teacher_action"] = "teacher_add_student"

        update = self._update("@NewStudent")
        self.assertTrue(await handle_teacher_message(update, self.context))

        self.assertEqual(update.effective_message.replies[-1][0], "Ученик @newstudent уже добавлен.")

    async def test_teacher_reactivates_inactive_student_message(self) -> None:
        self.db.add_student_access("newstudent")
        self.db.execute("UPDATE student_access SET is_active = 0 WHERE username = ?", ("newstudent",))
        self.context.user_data["teacher_action"] = "teacher_add_student"

        update = self._update("@NewStudent")
        self.assertTrue(await handle_teacher_message(update, self.context))

        self.assertTrue(self.db.is_active_student_access("newstudent"))
        self.assertEqual(update.effective_message.replies[-1][0], "Доступ для @newstudent снова включён ✅")

    async def test_teacher_rejects_invalid_student_username(self) -> None:
        self.context.user_data["teacher_action"] = "teacher_add_student"

        update = self._update("https://t.me/newstudent")
        self.assertTrue(await handle_teacher_message(update, self.context))

        self.assertFalse(self.db.is_active_student_access("https://t.me/newstudent"))
        self.assertEqual(update.effective_message.replies[-1][0], "Не похоже на Telegram username.\n\nВведите username в формате @username.")

    async def test_admin_remains_admin_but_visible_as_student_target(self) -> None:
        self.assertEqual(RoleResolver(RoleSettings(), self.db).role_for("wp_bvv"), Role.ADMIN)

        students = _student_users(self.context)

        self.assertTrue(any(student["username"] == "wp_bvv" and student["display_name"] == "Вова" for student in students))

    async def test_access_student_without_user_has_not_started_progress_message(self) -> None:
        self.db.add_student_access("newstudent")
        student = next(student for student in _student_users(self.context) if student["username"] == "newstudent")

        self.assertFalse(student["has_user"])
        self.assertEqual(_format_student_progress(self.db, student), NOT_STARTED_TEXT)

class StudentAccessValidationTests(unittest.TestCase):
    def test_normalize_username_removes_at_and_casefolds(self) -> None:
        from app.student_access_service import normalize_username

        self.assertEqual(normalize_username("@PrivetNormalno"), "privetnormalno")

    def test_validate_username_rejects_invalid_values(self) -> None:
        from app.student_access_service import normalize_username, validate_username

        invalid_values = ["", "ab", "with space", "https://t.me/user", "bad-name", "@"]
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertFalse(validate_username(normalize_username(value)))
