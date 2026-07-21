from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.database import Database
from app.handlers.student_lessons import (
    STUDENT_LESSON_OPEN_PREFIX,
    STUDENT_LESSON_START_PREFIX,
    STUDENT_LESSON_WORDS_PREFIX,
    handle_student_lesson_callback,
    handle_student_lesson_message,
)
from app.handlers.teacher import _format_lessons_screen
from app.keyboards import MY_LESSONS, TEACHER_LESSONS, main_menu_keyboard, teacher_menu_keyboard
from app.lesson_repository import LessonRepository
from app.lesson_runtime import LessonRuntimeService, LessonSection


@dataclass(frozen=True)
class Settings:
    allowed_usernames: frozenset[str] = frozenset({"student", "other"})
    admin_usernames: frozenset[str] = frozenset({"admin"})
    teacher_usernames: frozenset[str] = frozenset({"teacher"})
    display_names: dict[str, str] | None = None


class StudentLessonsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(1, "teacher", "Teacher")
        self.student = self.db.upsert_user(2, "student", "Student")
        self.other = self.db.upsert_user(3, "other", "Other")
        self.admin = self.db.upsert_user(4, "admin", "Admin")
        self.context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": self.db, "settings": Settings(display_names={})}), user_data={})

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def _message_update(self, text=MY_LESSONS, username="student", user_id=2):
        message = SimpleNamespace(text=text, replies=[])
        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))
        message.reply_text = reply_text
        return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, username=username), effective_message=message, callback_query=None)

    def _callback_update(self, data, username="student", user_id=2):
        message = SimpleNamespace(replies=[])
        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))
        message.reply_text = reply_text
        query = SimpleNamespace(data=data, message=message, edits=[], answered=False)
        async def answer():
            query.answered = True
        async def edit_message_text(text, reply_markup=None):
            query.edits.append((text, reply_markup))
        query.answer = answer
        query.edit_message_text = edit_message_text
        return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, username=username), effective_message=message, callback_query=query)

    def _lesson(self, title):
        return self.db.create_teacher_lesson(title, self.teacher["id"])

    async def test_student_without_lessons(self):
        update = self._message_update()
        self.assertTrue(await handle_student_lesson_message(update, self.context))
        self.assertIn("У вас пока нет назначенных уроков.", update.effective_message.replies[-1][0])
        buttons = [b.text for row in update.effective_message.replies[-1][1].inline_keyboard for b in row]
        self.assertEqual(buttons, ["⬅️ Меню"])

    async def test_student_with_lessons_and_ordering(self):
        old = self._lesson("Lesson 16 — Shopping")
        food = self._lesson("Lesson 15 — Food")
        present = self._lesson("Lesson 17 — Present Perfect")
        self.db.assign_lesson_to_student(old["id"], "student", self.teacher["id"])
        self.db.assign_lesson_to_student(present["id"], "student", self.teacher["id"])
        self.db.assign_lesson_to_student(food["id"], "student", self.teacher["id"])
        self.db.execute("UPDATE lesson_students SET assigned_at = '2026-01-01T00:00:00' WHERE lesson_id IN (?, ?)", (food["id"], present["id"]))
        self.db.execute("UPDATE lesson_students SET assigned_at = '2025-01-01T00:00:00' WHERE lesson_id = ?", (old["id"],))

        lessons = LessonRepository(self.db).list_student_lessons("student")
        self.assertEqual([l["lesson_number"] for l in lessons], [15, 17, 16])
        update = self._message_update()
        await handle_student_lesson_message(update, self.context)
        text = update.effective_message.replies[-1][0]
        self.assertIn("▶ Lesson 15 — Food", text)
        self.assertLess(text.index("Lesson 15"), text.index("Lesson 17"))
        self.assertLess(text.index("Lesson 17"), text.index("Lesson 16"))

    async def test_lesson_overview_progress_start_and_words_placeholder(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple", "pear", "bread"], self.teacher["id"])
        self.db.add_homework_task(lesson["id"], "text", "Do it")

        update = self._callback_update(f"{STUDENT_LESSON_OPEN_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)
        text = update.callback_query.edits[-1][0]
        self.assertIn("Lesson 15 — Food", text)
        self.assertIn("Не начат", text)
        self.assertIn("Прогресс урока", text)
        self.assertIn("🟢 Words", text)
        self.assertIn("⚪ Grammar", text)
        self.assertIn("⚪ Exercises", text)
        self.assertIn("⚪ Homework", text)
        self.assertIn("Words: 3", text)
        self.assertIn("Homework: 1", text)

        start = self._callback_update(f"{STUDENT_LESSON_START_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(start, self.context)
        start_text, start_keyboard = start.callback_query.edits[-1]
        self.assertIn("Следующий этап", start_text)
        self.assertIn("📖 Words", start_text)
        self.assertIn("3 слова", start_text)
        self.assertEqual([b.text for row in start_keyboard.inline_keyboard for b in row], ["▶ Открыть", "⬅️ Lesson"])

        words = self._callback_update(f"{STUDENT_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(words, self.context)
        words_text = words.callback_query.edits[-1][0]
        self.assertIn("📖 Words", words_text)
        self.assertIn("В этом уроке:", words_text)
        self.assertIn("3 слова", words_text)
        self.assertIn("Прохождение слов будет добавлено в следующем обновлении.", words_text)

    def test_runtime_returns_words_for_assigned_student(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])

        runtime = LessonRuntimeService(LessonRepository(self.db))

        self.assertEqual(runtime.get_next_section(lesson["id"], "student"), LessonSection.WORDS)
        self.assertIsNone(runtime.get_next_section(lesson["id"], "other"))

    async def test_student_cannot_open_other_or_missing_assignment(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "other", self.teacher["id"])
        update = self._callback_update(f"{STUDENT_LESSON_OPEN_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)
        self.assertEqual(update.callback_query.edits[-1][0], "Урок недоступен.")

        start = self._callback_update(f"{STUDENT_LESSON_START_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(start, self.context)
        self.assertEqual(start.callback_query.edits[-1][0], "Урок недоступен.")

        words = self._callback_update(f"{STUDENT_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(words, self.context)
        self.assertEqual(words.callback_query.edits[-1][0], "Урок недоступен.")

        self.db.unassign_lesson(lesson["id"])
        missing = self._callback_update(f"{STUDENT_LESSON_OPEN_PREFIX}{lesson['id']}", username="other", user_id=3)
        await handle_student_lesson_callback(missing, self.context)
        self.assertEqual(missing.callback_query.edits[-1][0], "Урок недоступен.")

    async def test_teacher_menu_unaffected_and_teacher_not_student_handler(self):
        self.assertIn(TEACHER_LESSONS, [b.text for row in teacher_menu_keyboard().keyboard for b in row])
        self.assertIn("📚 Lessons", _format_lessons_screen([]))
        update = self._message_update(username="teacher", user_id=1)
        self.assertFalse(await handle_student_lesson_message(update, self.context))

    async def test_admin_student_mode_works(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.context.user_data["impersonated_user_id"] = self.student["id"]
        update = self._message_update(username="admin", user_id=4)
        self.assertTrue(await handle_student_lesson_message(update, self.context))
        self.assertIn("Lesson 15 — Food", update.effective_message.replies[-1][0])

    def test_student_menu_has_lessons_and_legacy_practice(self):
        buttons = [b.text for row in main_menu_keyboard().keyboard for b in row]
        self.assertEqual(buttons[0], "📚 Мои уроки")
        self.assertIn("📚 Мой словарь", buttons)
        self.assertIn("🎯 Мои карточки", buttons)
        self.assertIn("🎮 Игра на 10 слов", buttons)
        self.assertIn("😵 Мои ошибки", buttons)
        self.assertIn("🔄 Обмен словами", buttons)


if __name__ == "__main__":
    unittest.main()
