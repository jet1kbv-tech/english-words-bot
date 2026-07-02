from dataclasses import dataclass
import unittest

from app.auth.roles import Role, RoleResolver, get_user_role, is_user_allowed
from app.handlers.teacher import _format_created_lesson, _format_teacher_lessons
from app.keyboards import TEACHER_CREATE_LESSON, TEACHER_LESSONS, TEACHER_MY_LESSONS, teacher_lessons_keyboard, teacher_menu_keyboard


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
