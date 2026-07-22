from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

from app.database import Database
from app.handlers.student_lessons import (
    STUDENT_LESSON_EXERCISE_TASK_PREFIX,
    STUDENT_LESSON_EXERCISES_PREFIX,
    STUDENT_LESSON_GRAMMAR_PREFIX,
    STUDENT_LESSON_HOMEWORK_PREFIX,
    STUDENT_LESSON_HOMEWORK_QUIZ_ANSWER_PREFIX,
    STUDENT_LESSON_HOMEWORK_TASK_PREFIX,
    STUDENT_LESSON_NEXT_STAGE_PREFIX,
    STUDENT_LESSON_OPEN_PREFIX,
    STUDENT_LESSON_START_PREFIX,
    STUDENT_LESSON_WORDS_CARDS_PREFIX,
    STUDENT_LESSON_WORDS_PREFIX,
    STUDENT_LESSON_WORDS_TYPE_PREFIX,
    handle_student_lesson_callback,
    handle_student_lesson_message,
)
from app.handlers.teacher import _format_lessons_screen
from app.keyboards import MY_LESSONS, TEACHER_LESSONS, main_menu_keyboard, teacher_menu_keyboard
from app.lesson_repository import LessonRepository
from app.lesson_runtime import LessonRuntimeService, LessonSection
from app.lesson_service import LessonService


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
        self.assertIn("🟢 Слова", text)
        self.assertIn("⚪ Грамматика", text)
        self.assertIn("⚪ Упражнения", text)
        self.assertIn("⚪ Домашнее задание", text)
        self.assertIn("Слова: 3", text)
        self.assertIn("Домашнее задание: 1", text)

        start = self._callback_update(f"{STUDENT_LESSON_START_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(start, self.context)
        start_text, start_keyboard = start.callback_query.edits[-1]
        self.assertIn("Следующий этап", start_text)
        self.assertIn("📖 Слова", start_text)
        self.assertIn("3 слова", start_text)
        self.assertEqual([b.text for row in start_keyboard.inline_keyboard for b in row], ["▶ Открыть", "▶ Далее", "⬅️ Урок"])

        words = self._callback_update(f"{STUDENT_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(words, self.context)
        words_text, words_keyboard = words.callback_query.edits[-1]
        self.assertIn("📖 Слова", words_text)
        self.assertIn("Слов в уроке: 3", words_text)
        self.assertIn("Выберите режим", words_text)
        self.assertEqual([b.text for row in words_keyboard.inline_keyboard for b in row], ["🃏 Карточки", "✍️ Ввод", "⬅️ Урок"])

    async def test_student_starts_lesson_words_cards_practice(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple", "pear", "bread"], self.teacher["id"])

        update = self._callback_update(f"{STUDENT_LESSON_WORDS_CARDS_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        session = self.context.user_data.get("training")
        self.assertIsNotNone(session)
        self.assertFalse(session["game"])
        self.assertEqual(len(session["words"]), 3)
        self.assertEqual(session["index"], 0)
        replies = "\n".join(reply for reply, _ in update.effective_message.replies)
        self.assertIn("Слова урока", replies)
        self.assertIn("Карточка 1/3", replies)

    async def test_student_starts_lesson_words_typed_practice(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple", "pear"], self.teacher["id"])

        update = self._callback_update(f"{STUDENT_LESSON_WORDS_TYPE_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        session = self.context.user_data.get("training")
        self.assertIsNotNone(session)
        self.assertTrue(session["game"])
        self.assertIsNotNone(session.get("session_id"))
        self.assertEqual(len(session["words"]), 2)
        replies = "\n".join(reply for reply, _ in update.effective_message.replies)
        self.assertIn("пиши ответы в чат", replies)
        self.assertIn("Напиши ответ в чат", replies)

    async def test_lesson_words_practice_empty_lesson_shows_message(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])

        update = self._callback_update(f"{STUDENT_LESSON_WORDS_CARDS_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        self.assertIsNone(self.context.user_data.get("training"))
        self.assertIn("пока нет слов", update.callback_query.edits[-1][0])

    async def test_student_cannot_start_practice_for_unassigned_lesson(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "other", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple"], self.teacher["id"])

        update = self._callback_update(f"{STUDENT_LESSON_WORDS_TYPE_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        self.assertIsNone(self.context.user_data.get("training"))
        self.assertEqual(update.callback_query.edits[-1][0], "Урок недоступен.")

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

    async def test_overview_shows_homework_button_only_when_tasks_exist(self):
        empty_lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(empty_lesson["id"], "student", self.teacher["id"])
        empty_update = self._callback_update(f"{STUDENT_LESSON_OPEN_PREFIX}{empty_lesson['id']}")
        await handle_student_lesson_callback(empty_update, self.context)
        empty_buttons = [b.text for row in empty_update.callback_query.edits[-1][1].inline_keyboard for b in row]
        self.assertNotIn("🏠 Домашнее задание", empty_buttons)

        lesson = self._lesson("Lesson 16 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_homework_task(lesson["id"], "free", "Write something")
        update = self._callback_update(f"{STUDENT_LESSON_OPEN_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)
        buttons = [b.text for row in update.callback_query.edits[-1][1].inline_keyboard for b in row]
        self.assertIn("🏠 Домашнее задание", buttons)

    async def test_homework_list_shows_status_icons(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        translation_task = self.db.add_homework_task(lesson["id"], "translation", "receipt", "чек")
        free_task = self.db.add_homework_task(lesson["id"], "free", "Write something")
        self.db.submit_homework_answer(translation_task["id"], self.student["id"], "чек", is_correct=True)
        self.db.submit_homework_answer(free_task["id"], self.student["id"], "my answer")

        update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        text, keyboard = update.callback_query.edits[-1]
        self.assertIn("✅", text)
        self.assertIn("⏳", text)
        buttons = [b.text for row in keyboard.inline_keyboard for b in row]
        self.assertTrue(any(b.startswith("✅") for b in buttons))
        self.assertTrue(any(b.startswith("⏳") for b in buttons))
        self.assertIn("⬅️ Урок", buttons)

    async def test_homework_list_empty_state(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])

        update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        self.assertIn("Пока нет заданий.", update.callback_query.edits[-1][0])

    async def test_translation_task_correct_answer_via_fallback(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "translation", "receipt", "чек")

        open_update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{lesson['id']}:{task['id']}")
        await handle_student_lesson_callback(open_update, self.context)
        self.assertIn("receipt", open_update.callback_query.edits[-1][0])
        self.assertIn("Напишите перевод в чат", open_update.callback_query.edits[-1][0])
        self.assertEqual(self.context.user_data.get("pending_homework_answer"), {"lesson_id": lesson["id"], "task_id": task["id"], "task_type": "translation"})

        with patch.dict(os.environ, {"AI_PROVIDER": "none"}):
            answer_update = self._message_update(text="чек")
            self.assertTrue(await handle_student_lesson_message(answer_update, self.context))

        self.assertIn("✅ Верно!", answer_update.effective_message.replies[-1][0])
        self.assertIsNone(self.context.user_data.get("pending_homework_answer"))
        latest = self.db.list_latest_homework_answers(lesson["id"], self.student["id"])
        self.assertTrue(latest[task["id"]]["is_correct"])

    async def test_translation_task_wrong_answer_shows_expected(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "translation", "receipt", "чек")
        open_update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{lesson['id']}:{task['id']}")
        await handle_student_lesson_callback(open_update, self.context)

        with patch.dict(os.environ, {"AI_PROVIDER": "none"}):
            answer_update = self._message_update(text="рецепт")
            self.assertTrue(await handle_student_lesson_message(answer_update, self.context))

        reply = answer_update.effective_message.replies[-1][0]
        self.assertIn("❌ Неверно.", reply)
        self.assertIn("Правильный ответ: чек", reply)

    async def test_translation_task_without_expected_answer_needs_manual_review(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "translation", "worth it")
        open_update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{lesson['id']}:{task['id']}")
        await handle_student_lesson_callback(open_update, self.context)

        with patch.dict(os.environ, {"AI_PROVIDER": "none"}):
            answer_update = self._message_update(text="стоит того")
            self.assertTrue(await handle_student_lesson_message(answer_update, self.context))

        self.assertIn("📤 Ответ отправлен на проверку.", answer_update.effective_message.replies[-1][0])
        latest = self.db.list_latest_homework_answers(lesson["id"], self.student["id"])
        self.assertIsNone(latest[task["id"]]["is_correct"])

    async def test_free_task_submission_is_pending_review(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "free", "Write two sentences with receipt")
        open_update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{lesson['id']}:{task['id']}")
        await handle_student_lesson_callback(open_update, self.context)
        self.assertIn("Напишите ответ в чат", open_update.callback_query.edits[-1][0])

        answer_update = self._message_update(text="I got the receipt. I kept the receipt.")
        self.assertTrue(await handle_student_lesson_message(answer_update, self.context))

        self.assertIn("📤 Ответ отправлен на проверку.", answer_update.effective_message.replies[-1][0])
        latest = self.db.list_latest_homework_answers(lesson["id"], self.student["id"])
        self.assertEqual(latest[task["id"]]["answer"], "I got the receipt. I kept the receipt.")
        self.assertIsNone(latest[task["id"]]["is_correct"])

    async def test_quiz_task_shows_options_and_checks_answer(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(
            lesson["id"], "quiz", "Choose the word",
            expected_answer="receipt",
            metadata_json='{"options": ["receipt", "recipe"], "correct_index": 0}',
        )

        open_update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{lesson['id']}:{task['id']}")
        await handle_student_lesson_callback(open_update, self.context)
        text, keyboard = open_update.callback_query.edits[-1]
        self.assertIn("Choose the word", text)
        self.assertEqual([b.text for row in keyboard.inline_keyboard for b in row], ["receipt", "recipe", "⬅️ Домашнее задание"])

        wrong = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_QUIZ_ANSWER_PREFIX}{lesson['id']}:{task['id']}:1")
        await handle_student_lesson_callback(wrong, self.context)
        self.assertIn("❌ Неверно.", wrong.callback_query.edits[-1][0])
        self.assertIn("Правильный ответ: receipt", wrong.callback_query.edits[-1][0])

        correct = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_QUIZ_ANSWER_PREFIX}{lesson['id']}:{task['id']}:0")
        await handle_student_lesson_callback(correct, self.context)
        self.assertIn("✅ Верно!", correct.callback_query.edits[-1][0])

        latest = self.db.list_latest_homework_answers(lesson["id"], self.student["id"])
        self.assertTrue(latest[task["id"]]["is_correct"])
        self.assertEqual(latest[task["id"]]["answer"], "receipt")

    async def test_quiz_answer_rejects_out_of_range_option(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(
            lesson["id"], "quiz", "Choose the word",
            expected_answer="receipt",
            metadata_json='{"options": ["receipt", "recipe"], "correct_index": 0}',
        )

        update = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_QUIZ_ANSWER_PREFIX}{lesson['id']}:{task['id']}:9")
        await handle_student_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
        self.assertEqual(self.db.list_latest_homework_answers(lesson["id"], self.student["id"]), {})

    async def test_homework_task_lookup_is_lesson_scoped(self):
        food = self._lesson("Lesson 15 — Food")
        travel = self._lesson("Lesson 16 — Travel")
        self.db.assign_lesson_to_student(food["id"], "student", self.teacher["id"])
        self.db.assign_lesson_to_student(travel["id"], "student", self.teacher["id"])
        task = self.db.add_homework_task(food["id"], "free", "Write something")

        wrong_lesson = self._callback_update(f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{travel['id']}:{task['id']}")
        await handle_student_lesson_callback(wrong_lesson, self.context)

        self.assertEqual(wrong_lesson.callback_query.edits[-1][0], "Задание не найдено.")

    async def test_student_cannot_access_homework_for_unassigned_lesson(self):
        lesson = self._lesson("Lesson 15 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "other", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "free", "Write something")

        for data in (
            f"{STUDENT_LESSON_HOMEWORK_PREFIX}{lesson['id']}",
            f"{STUDENT_LESSON_HOMEWORK_TASK_PREFIX}{lesson['id']}:{task['id']}",
        ):
            with self.subTest(data=data):
                update = self._callback_update(data)
                await handle_student_lesson_callback(update, self.context)
                self.assertEqual(update.callback_query.edits[-1][0], "Урок недоступен.")

    async def test_teacher_menu_unaffected_and_teacher_not_student_handler(self):
        self.assertIn(TEACHER_LESSONS, [b.text for row in teacher_menu_keyboard().keyboard for b in row])
        self.assertIn("📚 Уроки", _format_lessons_screen([]))
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


class LessonRuntimeProgressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(1, "teacher", "Teacher")
        self.student = self.db.upsert_user(2, "student", "Student")
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

    async def _next_stage(self, lesson_id):
        update = self._callback_update(f"{STUDENT_LESSON_NEXT_STAGE_PREFIX}{lesson_id}")
        await handle_student_lesson_callback(update, self.context)
        return update.callback_query.edits[-1]

    async def test_words_only_lesson_advances_straight_to_finished(self):
        lesson = self._lesson("Lesson 1 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple"], self.teacher["id"])

        text, keyboard = await self._next_stage(lesson["id"])

        self.assertIn("🎉 Урок завершён", text)
        self.assertEqual([b.text for row in keyboard.inline_keyboard for b in row], ["⬅️ Мои уроки"])

        repo = LessonRepository(self.db)
        self.assertEqual(LessonRuntimeService(repo).get_next_section(lesson["id"], "student"), LessonSection.FINISHED)

    async def test_empty_grammar_and_exercises_are_skipped(self):
        lesson = self._lesson("Lesson 2 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple"], self.teacher["id"])
        self.db.add_homework_task(lesson["id"], "free", "Write something")

        text, _keyboard = await self._next_stage(lesson["id"])

        self.assertIn("🏠 Домашнее задание", text)
        repo = LessonRepository(self.db)
        self.assertEqual(LessonRuntimeService(repo).get_next_section(lesson["id"], "student"), LessonSection.HOMEWORK)

    async def test_full_progression_through_all_sections(self):
        lesson = self._lesson("Lesson 3 — Present Simple")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["apple"], self.teacher["id"])
        repo = LessonRepository(self.db)
        service = LessonService(repo)
        service.add_grammar_item(lesson["id"], "Present Simple", "Use base verb form.", "I work every day.")
        service.add_exercise_item(lesson["id"], "I ___ (work) every day.", "work", "base form")
        service.add_translation_task(lesson["id"], "receipt", "чек")

        words_to_grammar_text, _kb = await self._next_stage(lesson["id"])
        self.assertIn("📝 Грамматика", words_to_grammar_text)

        grammar_update = self._callback_update(f"{STUDENT_LESSON_GRAMMAR_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(grammar_update, self.context)
        grammar_text = grammar_update.callback_query.edits[-1][0]
        self.assertIn("Present Simple", grammar_text)
        self.assertIn("Use base verb form.", grammar_text)
        self.assertIn("Example: I work every day.", grammar_text)

        grammar_to_exercises_text, _kb = await self._next_stage(lesson["id"])
        self.assertIn("✏️ Упражнения", grammar_to_exercises_text)

        exercises_update = self._callback_update(f"{STUDENT_LESSON_EXERCISES_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(exercises_update, self.context)
        exercises_text = exercises_update.callback_query.edits[-1][0]
        self.assertIn("I ___ (work) every day.", exercises_text)
        self.assertIn("⚪", exercises_text)

        item = service.list_exercise_items(lesson["id"])[0]
        open_task = self._callback_update(f"{STUDENT_LESSON_EXERCISE_TASK_PREFIX}{lesson['id']}:{item['id']}")
        await handle_student_lesson_callback(open_task, self.context)
        self.assertIn("I ___ (work) every day.", open_task.callback_query.edits[-1][0])
        self.assertEqual(self.context.user_data.get("pending_exercise_answer"), {"lesson_id": lesson["id"], "exercise_id": item["id"]})

        answer_update = self._message_update(text="Work")
        self.assertTrue(await handle_student_lesson_message(answer_update, self.context))
        self.assertIn("✅ Верно!", answer_update.effective_message.replies[-1][0])
        self.assertIsNone(self.context.user_data.get("pending_exercise_answer"))

        exercises_to_homework_text, _kb = await self._next_stage(lesson["id"])
        self.assertIn("🏠 Домашнее задание", exercises_to_homework_text)

        finish_text, finish_kb = await self._next_stage(lesson["id"])
        self.assertIn("🎉 Урок завершён", finish_text)
        self.assertEqual([b.text for row in finish_kb.inline_keyboard for b in row], ["⬅️ Мои уроки"])

    async def test_exercise_wrong_answer_shows_expected_and_hint(self):
        lesson = self._lesson("Lesson 4 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        repo = LessonRepository(self.db)
        service = LessonService(repo)
        item = service.add_exercise_item(lesson["id"], "I ___ (work) every day.", "work", "base form, no -s")

        open_task = self._callback_update(f"{STUDENT_LESSON_EXERCISE_TASK_PREFIX}{lesson['id']}:{item['id']}")
        await handle_student_lesson_callback(open_task, self.context)

        answer_update = self._message_update(text="works")
        await handle_student_lesson_message(answer_update, self.context)
        reply = answer_update.effective_message.replies[-1][0]
        self.assertIn("❌ Неверно.", reply)
        self.assertIn("Правильный ответ: work", reply)
        self.assertIn("Подсказка: base form, no -s", reply)

    async def test_grammar_empty_state_message(self):
        lesson = self._lesson("Lesson 5 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])

        update = self._callback_update(f"{STUDENT_LESSON_GRAMMAR_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(update, self.context)

        self.assertIn("В этом уроке пока нет грамматики.", update.callback_query.edits[-1][0])

    async def test_resume_after_exit_shows_persisted_current_section(self):
        lesson = self._lesson("Lesson 6 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        repo = LessonRepository(self.db)
        service = LessonService(repo)
        service.add_grammar_item(lesson["id"], "Topic", "Explanation")

        await self._next_stage(lesson["id"])  # advance WORDS -> GRAMMAR, persisted

        start_update = self._callback_update(f"{STUDENT_LESSON_START_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(start_update, self.context)
        start_text = start_update.callback_query.edits[-1][0]
        self.assertIn("📝 Грамматика", start_text)

    async def test_overview_icons_reflect_current_section(self):
        lesson = self._lesson("Lesson 7 — Food")
        self.db.assign_lesson_to_student(lesson["id"], "student", self.teacher["id"])
        repo = LessonRepository(self.db)
        service = LessonService(repo)
        service.add_grammar_item(lesson["id"], "Topic", "Explanation")

        await self._next_stage(lesson["id"])  # WORDS -> GRAMMAR

        overview_update = self._callback_update(f"{STUDENT_LESSON_OPEN_PREFIX}{lesson['id']}")
        await handle_student_lesson_callback(overview_update, self.context)
        overview_text = overview_update.callback_query.edits[-1][0]
        self.assertIn("В процессе", overview_text)
        self.assertIn("✅ Слова", overview_text)
        self.assertIn("🟢 Грамматика", overview_text)
        self.assertIn("⚪ Упражнения", overview_text)


if __name__ == "__main__":
    unittest.main()
