from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.database import Database
from app.handlers.menu import handle_help_message, handle_tutorial_message
from app.keyboards import HELP_GETTING_STARTED, HELP, teacher_menu_keyboard, main_menu_keyboard
from app.notifications.notification_service import NotificationService
from app.tutorial.tutorial_models import TutorialStep
from app.tutorial.tutorial_registry import STUDENT_ONBOARDING, TEACHER_ONBOARDING, get_tutorial
from app.tutorial.tutorial_service import TUTORIAL_FINISH, TUTORIAL_NEXT, current_tutorial, should_start_first_run, start_tutorial_state


class Settings:
    allowed_usernames = frozenset({"student"})
    teacher_usernames = frozenset({"teacher"})
    admin_usernames = frozenset({"admin"})
    display_names = {}


class TutorialNotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.sqlite3")
        self.db.init_schema()
        self.student = self.db.upsert_user(10, "student", "Student")
        self.teacher = self.db.upsert_user(20, "teacher", "Teacher")
        self.context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": self.db, "settings": Settings()}), user_data={})

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def update(self, text, username="student", user_id=10):
        message = SimpleNamespace(text=text, replies=[])
        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))
        message.reply_text = reply_text
        return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, username=username), effective_message=message)

    def test_registry_and_models(self):
        student = get_tutorial(STUDENT_ONBOARDING)
        teacher = get_tutorial(TEACHER_ONBOARDING)
        self.assertIsNotNone(student)
        self.assertIsNotNone(teacher)
        self.assertEqual(len(student.steps), 5)
        self.assertEqual(len(teacher.steps), 4)
        self.assertTrue(hasattr(TutorialStep("t", "x"), "feature_key"))

    def test_tutorial_progress(self):
        self.assertFalse(self.db.has_completed_tutorial(self.student["id"], STUDENT_ONBOARDING))
        self.db.mark_tutorial_completed(self.student["id"], "student", STUDENT_ONBOARDING)
        self.assertTrue(self.db.has_completed_tutorial(self.student["id"], STUDENT_ONBOARDING))
        self.db.reset_tutorial(self.student["id"], STUDENT_ONBOARDING)
        self.assertFalse(self.db.has_completed_tutorial(self.student["id"], STUDENT_ONBOARDING))

    async def test_first_run_repeat_and_invalid_step(self):
        self.assertTrue(should_start_first_run(self.db, self.student["id"], "STUDENT"))
        self.db.mark_tutorial_completed(self.student["id"], "student", STUDENT_ONBOARDING)
        self.assertFalse(should_start_first_run(self.db, self.student["id"], "STUDENT"))

        await handle_help_message(self.update(HELP), self.context)
        update = self.update(HELP_GETTING_STARTED)
        self.assertTrue(await handle_help_message(update, self.context))
        self.assertIn("Шаг 1 из 5", update.effective_message.replies[-1][0])
        self.context.user_data["tutorial_state"]["step"] = 999
        tutorial, step, first_run = current_tutorial(self.context)
        self.assertEqual(step, 0)
        self.assertFalse(first_run)

    async def test_completing_first_run_returns_to_role_menu(self):
        start_tutorial_state(self.context, STUDENT_ONBOARDING, first_run=True)
        update = self.update(TUTORIAL_FINISH)
        # Move to last step so finish button is accepted as completion.
        self.context.user_data["tutorial_state"]["step"] = 4
        self.assertTrue(await handle_tutorial_message(update, self.context))
        self.assertTrue(self.db.has_completed_tutorial(self.student["id"], STUDENT_ONBOARDING))
        buttons = [button.text for row in update.effective_message.replies[-1][1].keyboard for button in row]
        self.assertIn("❓ Помощь", buttons)

    def test_product_notifications_table_and_service(self):
        rows = self.db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'product_notifications'")
        self.assertEqual(len(rows), 1)
        service = NotificationService(self.db)
        service.create_product_notification("new", "STUDENT", "Title", "Body", "feature")
        service.create_product_notification("teacher", "TEACHER", "Teacher", "Body")
        active = service.list_active_product_notifications("STUDENT")
        self.assertEqual([row["key"] for row in active], ["new"])

    async def test_lesson_assignment_notifications_best_effort(self):
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        assignment = self.db.assign_lesson_to_student(lesson["id"], "missing", self.teacher["id"])
        sent = await NotificationService(self.db).notify_lesson_assigned(SimpleNamespace(), "missing", lesson)
        self.assertIsNotNone(assignment)
        self.assertFalse(sent)

        class Bot:
            def __init__(self):
                self.messages = []
            async def send_message(self, chat_id, text):
                self.messages.append((chat_id, text))

        bot = Bot()
        sent = await NotificationService(self.db).notify_lesson_assigned(bot, "student", lesson)
        self.assertTrue(sent)
        self.assertEqual(bot.messages[0][0], 10)
        self.assertIn("📚 Вам назначен новый урок", bot.messages[0][1])

        class FailingBot:
            async def send_message(self, chat_id, text):
                raise RuntimeError("boom")

        self.assertFalse(await NotificationService(self.db).notify_lesson_assigned(FailingBot(), "student", lesson))
        self.assertIsNotNone(self.db.get_active_lesson_assignment(lesson["id"]))

    async def test_homework_assignment_notifications_best_effort(self):
        lesson = self.db.create_teacher_lesson("Lesson 16 — Food", self.teacher["id"])
        task = self.db.add_homework_task(lesson["id"], "translation", "receipt", "чек")

        sent = await NotificationService(self.db).notify_homework_assigned(SimpleNamespace(), "missing", lesson, task)
        self.assertFalse(sent)

        class Bot:
            def __init__(self):
                self.messages = []
            async def send_message(self, chat_id, text):
                self.messages.append((chat_id, text))

        bot = Bot()
        sent = await NotificationService(self.db).notify_homework_assigned(bot, "student", lesson, task)
        self.assertTrue(sent)
        self.assertEqual(bot.messages[0][0], 10)
        self.assertIn("🏠 Новое домашнее задание", bot.messages[0][1])
        self.assertIn("Задание: receipt", bot.messages[0][1])

        class FailingBot:
            async def send_message(self, chat_id, text):
                raise RuntimeError("boom")

        self.assertFalse(await NotificationService(self.db).notify_homework_assigned(FailingBot(), "student", lesson, task))
