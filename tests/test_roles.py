from dataclasses import dataclass
import unittest

from app.auth.roles import Role, RoleResolver, get_user_role, is_user_allowed
from app.lesson_metadata import lesson_display_name
from app.handlers.teacher import TEACHER_LESSON_AI_PREFIX, TEACHER_LESSON_ASSIGN_PREFIX, TEACHER_LESSON_ASSIGN_STUDENT_PREFIX, TEACHER_LESSON_UNASSIGN_PREFIX, _format_assign_student_screen, _assign_student_keyboard, TEACHER_LESSON_WORDS_ADD_PREFIX, TEACHER_LESSON_WORDS_SELECT_PREFIX, TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX, TEACHER_LESSON_WORDS_SELECT_ALL_PREFIX, TEACHER_LESSON_WORDS_SELECT_CLEAR_PREFIX, TEACHER_LESSON_WORDS_SELECT_DONE_PREFIX, TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX, TEACHER_LESSON_WORDS_AI_APPLY_PREFIX, TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX, TEACHER_LESSON_WORDS_AI_EDIT_PREFIX, TEACHER_LESSON_WORD_OPEN_PREFIX, TEACHER_LESSON_WORD_EDIT_PREFIX, TEACHER_LESSON_WORDS_CANCEL_PREFIX, TEACHER_LESSON_WORDS_CONFIRM_PREFIX, TEACHER_LESSON_BACK_PREFIX, TEACHER_LESSON_EXERCISES_PREFIX, TEACHER_LESSON_GRAMMAR_PREFIX, TEACHER_LESSON_HOMEWORK_PREFIX, TEACHER_LESSON_WORDS_PREFIX, _format_created_lesson, _format_lesson_detail, _format_lessons_screen, _format_lesson_section, _format_teacher_lessons, _format_student_progress, _student_users, handle_teacher_lesson_callback, handle_teacher_message, NOT_STARTED_TEXT
from app.lesson_service import normalize_lesson_words_import
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


    def test_normalize_lesson_words_import_trims_drops_empty_and_deduplicates(self) -> None:
        self.assertEqual(normalize_lesson_words_import(" receipt \n\nworth it\nreceipt\n stale "), ["receipt", "worth it", "stale"])

    def test_teacher_menu_has_lessons_button(self) -> None:
        self.assertIn(TEACHER_LESSONS, self._texts(teacher_menu_keyboard()))

    def test_teacher_lessons_menu_has_create_and_back(self) -> None:
        self.assertEqual(self._texts(teacher_lessons_keyboard())[:2], [TEACHER_CREATE_LESSON, "⬅️ Назад"])


    def test_lessons_screen_empty_state(self) -> None:
        self.assertIn("Пока нет уроков.", _format_lessons_screen([]))

    def test_lesson_detail_shows_dash_without_assignment(self) -> None:
        formatted = _format_lesson_detail({"title": "Lesson 15 — Food", "lesson_number": 15, "topic": "Food", "description": None, "level": None, "status": "DRAFT", "words_count": 0, "grammar_count": 0, "exercises_count": 0, "homework_count": 0})
        self.assertIn("👤 Student", formatted)
        self.assertIn("\n—\n", formatted)

    def test_lesson_detail_shows_active_student(self) -> None:
        formatted = _format_lesson_detail({"title": "Lesson 15 — Food", "lesson_number": 15, "topic": "Food", "description": None, "level": None, "status": "DRAFT", "words_count": 0, "grammar_count": 0, "exercises_count": 0, "homework_count": 0}, {"student_username": "privetnormalno"})
        self.assertIn("@privetnormalno", formatted)

    def test_assign_screen_lists_available_student_targets(self) -> None:
        summary = {"title": "Lesson 15 — Food", "lesson_number": 15, "topic": "Food"}
        students = [{"username": "privetnormalno"}, {"username": "wp_bvv"}]
        self.assertIn("Выберите ученика", _format_assign_student_screen(summary, students))
        buttons = [button.text for row in _assign_student_keyboard(15, students).inline_keyboard for button in row]
        self.assertIn("@privetnormalno", buttons)
        self.assertIn("@wp_bvv", buttons)

    def test_lesson_detail_formatter_shows_counts(self) -> None:
        summary = {
            "title": "Lesson 15 — Food",
            "lesson_number": 15,
            "topic": "Food",
            "description": None,
            "level": None,
            "status": "DRAFT",
            "words_count": 2,
            "grammar_count": 0,
            "exercises_count": 0,
            "homework_count": 1,
        }

        formatted = _format_lesson_detail(summary)

        self.assertIn("Lesson: Lesson 15 — Food", formatted)
        self.assertIn("Topic: Food", formatted)
        self.assertIn("Level: —", formatted)
        self.assertIn("Description: —", formatted)
        self.assertIn("Status: Draft", formatted)
        self.assertIn("📖 Words: 2", formatted)
        self.assertIn("📝 Grammar: 0", formatted)
        self.assertIn("✏️ Exercises: 0", formatted)
        self.assertIn("🏠 Homework: 1", formatted)

    def test_lesson_display_name_and_list_use_metadata(self) -> None:
        self.assertEqual(lesson_display_name({"title": "Raw", "lesson_number": 15, "topic": "Food"}), "Lesson 15 — Food")
        self.assertEqual(lesson_display_name({"title": "Raw", "lesson_number": None, "topic": "Travel"}), "Travel")
        self.assertEqual(lesson_display_name({"title": "Legacy", "lesson_number": None, "topic": None}), "Legacy")

        formatted = _format_lessons_screen([
            {"id": 1, "title": "Lesson 15 — Food", "lesson_number": 15, "topic": "Food", "status": "DRAFT"},
            {"id": 2, "title": "Legacy", "lesson_number": None, "topic": None, "status": "DRAFT"},
        ])

        self.assertIn("1. Lesson 15 — Food — Draft", formatted)
        self.assertIn("2. Legacy — Draft", formatted)

    def test_lesson_section_uses_display_name(self) -> None:
        formatted = _format_lesson_section({"title": "Raw", "lesson_number": 15, "topic": "Food"}, "words")

        self.assertIn("Lesson: Lesson 15 — Food", formatted)

    def test_lesson_formatters_show_requested_fields(self) -> None:
        lesson = {"title": "Past Simple", "theme": None, "grammar_topic": "Past Simple", "status": "DRAFT"}
        student = {"display_name": "Student", "username": "student"}

        created = _format_created_lesson(lesson, student)

        self.assertIn("Урок создан", created)
        self.assertIn("title: Past Simple", created)
        self.assertIn("student: Student (@student)", created)
        self.assertIn("theme: -", created)
        self.assertIn("grammar_topic: Past Simple", created)
        self.assertIn("status=DRAFT", created)

    def test_my_lessons_formatter_shows_title_student_theme_status(self) -> None:
        lesson = {
            "title": "Past Simple",
            "student_display_name": "Student",
            "student_username": "student",
            "theme": "Travel",
            "status": "DRAFT",
        }

        formatted = _format_teacher_lessons([lesson])

        self.assertIn("Past Simple", formatted)
        self.assertIn("Student (@student)", formatted)
        self.assertIn("theme: Travel", formatted)
        self.assertIn("status: DRAFT", formatted)


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

    def _callback_update(self, data: str, username: str = "romateaches", user_id: int = 101):
        message = self.SimpleNamespace(replies=[])
        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))
        message.reply_text = reply_text
        query = self.SimpleNamespace(data=data, message=message, edits=[], answered=False)
        async def answer():
            query.answered = True
        async def edit_message_text(text, reply_markup=None):
            query.edits.append((text, reply_markup))
        query.answer = answer
        query.edit_message_text = edit_message_text
        return self.SimpleNamespace(effective_user=self.SimpleNamespace(id=user_id, username=username), effective_message=message, callback_query=query)


    async def test_teacher_can_open_lessons_screen(self) -> None:
        update = self._update(TEACHER_LESSONS)

        self.assertTrue(await handle_teacher_message(update, self.context))
        self.assertIn("📚 Lessons", update.effective_message.replies[-1][0])

    async def test_student_cannot_access_teacher_lessons_handler(self) -> None:
        update = self._update(TEACHER_LESSONS)
        update.effective_user = self.SimpleNamespace(id=103, username="privetnormalno")

        self.assertFalse(await handle_teacher_message(update, self.context))
        self.assertEqual(update.effective_message.replies, [])


    async def test_lesson_section_callbacks_show_placeholders_and_back(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        for prefix, expected in [
            (TEACHER_LESSON_WORDS_PREFIX, "В этом уроке пока нет слов."),
            (TEACHER_LESSON_GRAMMAR_PREFIX, "Этот раздел скоро позволит добавлять грамматическую тему и объяснения."),
            (TEACHER_LESSON_EXERCISES_PREFIX, "Этот раздел скоро позволит добавлять упражнения урока."),
            (TEACHER_LESSON_HOMEWORK_PREFIX, "Этот раздел скоро позволит собрать домашнее задание по уроку."),
            (TEACHER_LESSON_AI_PREFIX, "Скоро здесь можно будет сгенерировать слова"),
        ]:
            with self.subTest(prefix=prefix):
                update = self._callback_update(f"{prefix}{lesson['id']}")

                await handle_teacher_lesson_callback(update, self.context)

                self.assertIn(expected, update.callback_query.edits[-1][0])
                if prefix != TEACHER_LESSON_WORDS_PREFIX:
                    self.assertIn("Lesson: Lesson 15 — Food", update.callback_query.edits[-1][0])

        back = self._callback_update(f"{TEACHER_LESSON_BACK_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(back, self.context)

        self.assertIn("📚 Lesson", back.callback_query.edits[-1][0])
        self.assertIn("📖 Words: 0", back.callback_query.edits[-1][0])

    async def test_lesson_section_callback_missing_lesson_is_safe(self) -> None:
        update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}999")

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.message.replies[-1][0], "Lesson не найден.")

    async def test_student_cannot_access_lesson_section_callbacks(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}{lesson['id']}", username="privetnormalno", user_id=103)

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
        self.assertEqual(update.callback_query.message.replies, [])


    async def test_words_list_shows_word_buttons_and_word_detail_flow(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it", "stale"], self.teacher["id"])
        words = self.db.list_lesson_words(lesson["id"])

        open_update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(open_update, self.context)

        self.assertIn("Всего слов: 3", open_update.callback_query.edits[-1][0])
        buttons = [button.text for row in open_update.callback_query.edits[-1][1].inline_keyboard for button in row]
        self.assertIn("receipt", buttons)
        self.assertIn("worth it", buttons)
        self.assertIn("stale", buttons)

        detail_update = self._callback_update(f"{TEACHER_LESSON_WORD_OPEN_PREFIX}{lesson['id']}:{words[0]['word_id']}")
        await handle_teacher_lesson_callback(detail_update, self.context)

        self.assertIn("📖 Word", detail_update.callback_query.edits[-1][0])
        self.assertIn("Lesson: Lesson 15 — Food", detail_update.callback_query.edits[-1][0])
        self.assertIn("English: receipt", detail_update.callback_query.edits[-1][0])
        self.assertIn("Translation: —", detail_update.callback_query.edits[-1][0])
        self.assertIn("Example: —", detail_update.callback_query.edits[-1][0])
        self.assertIn("Topic: —", detail_update.callback_query.edits[-1][0])

        back_update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(back_update, self.context)

        self.assertIn("📖 Words", back_update.callback_query.edits[-1][0])
        self.assertIn("• receipt", back_update.callback_query.edits[-1][0])

    async def test_word_detail_missing_or_wrong_lesson_is_safe(self) -> None:
        first_lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        second_lesson = self.db.create_teacher_lesson("Lesson 16 — Travel", self.teacher["id"])
        self.db.add_lesson_words(first_lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(first_lesson["id"])[0]

        wrong_lesson_update = self._callback_update(f"{TEACHER_LESSON_WORD_OPEN_PREFIX}{second_lesson['id']}:{word['word_id']}")
        await handle_teacher_lesson_callback(wrong_lesson_update, self.context)

        self.assertEqual(wrong_lesson_update.callback_query.edits[-1][0], "Word не найден.")

        missing_update = self._callback_update(f"{TEACHER_LESSON_WORD_OPEN_PREFIX}{first_lesson['id']}:999")
        await handle_teacher_lesson_callback(missing_update, self.context)

        self.assertEqual(missing_update.callback_query.edits[-1][0], "Word не найден.")

    async def test_student_cannot_access_word_detail_callback(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]
        update = self._callback_update(
            f"{TEACHER_LESSON_WORD_OPEN_PREFIX}{lesson['id']}:{word['word_id']}", username="privetnormalno", user_id=103
        )

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
        self.assertEqual(update.callback_query.message.replies, [])


    async def test_teacher_can_update_word_detail_fields_and_cleanup_state(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word_id = self.db.list_lesson_words(lesson["id"])[0]["word_id"]

        for field, callback_label, value, expected_line in [
            ("translation", "Translation", " чек ", "Translation: чек"),
            ("example", "Example", "Can I have the receipt, please?", "Example: Can I have the receipt, please?"),
            ("topic", "Topic", " Shopping ", "Topic: Shopping"),
        ]:
            with self.subTest(field=field):
                edit_update = self._callback_update(f"{TEACHER_LESSON_WORD_EDIT_PREFIX}{field}:{lesson['id']}:{word_id}")
                await handle_teacher_lesson_callback(edit_update, self.context)
                self.assertIn(f"Введите {('перевод слова' if field == 'translation' else 'пример для слова' if field == 'example' else 'topic для слова')}", edit_update.callback_query.edits[-1][0])
                self.assertIn("Чтобы очистить поле", edit_update.callback_query.edits[-1][0])

                message_update = self._update(value)
                self.assertTrue(await handle_teacher_message(message_update, self.context))

                self.assertIn(expected_line, message_update.effective_message.replies[-1][0])
                self.assertIsNone(self.context.user_data.get("teacher_action"))
                self.assertIsNone(self.context.user_data.get("pending_lesson_word_edit"))

    async def test_teacher_can_clear_word_detail_value_and_return_to_detail(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word_id = self.db.list_lesson_words(lesson["id"])[0]["word_id"]
        self.db.update_word_translation(lesson["id"], word_id, "чек")

        edit_update = self._callback_update(f"{TEACHER_LESSON_WORD_EDIT_PREFIX}translation:{lesson['id']}:{word_id}")
        await handle_teacher_lesson_callback(edit_update, self.context)
        message_update = self._update("пусто")

        self.assertTrue(await handle_teacher_message(message_update, self.context))

        self.assertIn("📖 Word", message_update.effective_message.replies[-1][0])
        self.assertIn("Translation: —", message_update.effective_message.replies[-1][0])
        buttons = [button.text for row in message_update.effective_message.replies[-1][1].inline_keyboard for button in row]
        self.assertIn("⬅️ Words", buttons)

    async def test_student_cannot_start_word_detail_edit_callback(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word_id = self.db.list_lesson_words(lesson["id"])[0]["word_id"]
        update = self._callback_update(
            f"{TEACHER_LESSON_WORD_EDIT_PREFIX}translation:{lesson['id']}:{word_id}", username="privetnormalno", user_id=103
        )

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
        self.assertEqual(update.callback_query.message.replies, [])
        self.assertIsNone(self.context.user_data.get("pending_lesson_word_edit"))

    async def test_word_detail_has_edit_buttons(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word_id = self.db.list_lesson_words(lesson["id"])[0]["word_id"]

        detail_update = self._callback_update(f"{TEACHER_LESSON_WORD_OPEN_PREFIX}{lesson['id']}:{word_id}")
        await handle_teacher_lesson_callback(detail_update, self.context)

        buttons = [button.text for row in detail_update.callback_query.edits[-1][1].inline_keyboard for button in row]
        self.assertEqual(buttons, ["✏️ Translation", "✏️ Example", "✏️ Topic", "⬅️ Words"])

    async def test_teacher_import_words_preview_confirm_and_order(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 20 — Food", self.teacher["id"])
        open_update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(open_update, self.context)
        self.assertIn("В этом уроке пока нет слов.", open_update.callback_query.edits[-1][0])

        add_update = self._callback_update(f"{TEACHER_LESSON_WORDS_ADD_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(add_update, self.context)
        self.assertIn("Отправьте список слов.", add_update.callback_query.message.replies[-1][0])

        message_update = self._update(" receipt \n\nworth it\nreceipt\nstale")
        self.assertTrue(await handle_teacher_message(message_update, self.context))
        self.assertIn("1. receipt", message_update.effective_message.replies[-1][0])
        self.assertNotIn("receipt\n2. receipt", message_update.effective_message.replies[-1][0])

        confirm_update = self._callback_update(f"{TEACHER_LESSON_WORDS_CONFIRM_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(confirm_update, self.context)

        self.assertEqual([word["text"] for word in self.db.list_lesson_words(lesson["id"])], ["receipt", "worth it", "stale"])
        self.assertIn("Всего слов: 3", confirm_update.callback_query.edits[-1][0])

    async def test_teacher_import_words_cancel_does_not_save(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 21 — Food", self.teacher["id"])
        add_update = self._callback_update(f"{TEACHER_LESSON_WORDS_ADD_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(add_update, self.context)
        message_update = self._update("receipt")
        self.assertTrue(await handle_teacher_message(message_update, self.context))

        cancel_update = self._callback_update(f"{TEACHER_LESSON_WORDS_CANCEL_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(cancel_update, self.context)

        self.assertEqual(self.db.list_lesson_words(lesson["id"]), [])
        self.assertIn("В этом уроке пока нет слов.", cancel_update.callback_query.edits[-1][0])

    async def test_student_cannot_start_words_import(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 22 — Food", self.teacher["id"])
        update = self._callback_update(f"{TEACHER_LESSON_WORDS_ADD_PREFIX}{lesson['id']}", username="privetnormalno", user_id=103)

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.message.replies, [])
        self.assertIsNone(self.context.user_data.get("pending_lesson_words"))


    async def test_words_screen_select_button_only_with_words(self) -> None:
        empty_lesson = self.db.create_teacher_lesson("Lesson 23 — Empty", self.teacher["id"])
        empty_update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}{empty_lesson['id']}")
        await handle_teacher_lesson_callback(empty_update, self.context)
        empty_buttons = [button.text for row in empty_update.callback_query.edits[-1][1].inline_keyboard for button in row]
        self.assertNotIn("☑️ Выбрать", empty_buttons)

        lesson = self.db.create_teacher_lesson("Lesson 24 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        update = self._callback_update(f"{TEACHER_LESSON_WORDS_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(update, self.context)
        buttons = [button.text for row in update.callback_query.edits[-1][1].inline_keyboard for button in row]
        self.assertIn("☑️ Выбрать", buttons)

    async def test_teacher_can_select_toggle_clear_all_and_done_lesson_words(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 25 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it", "stale"], self.teacher["id"])
        words = self.db.list_lesson_words(lesson["id"])

        select_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(select_update, self.context)
        self.assertIn("📖 Words — выбор", select_update.callback_query.edits[-1][0])
        self.assertIn("Выбрано: 0 из 3", select_update.callback_query.edits[-1][0])
        self.assertIn("☐ receipt", select_update.callback_query.edits[-1][0])

        toggle_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX}{lesson['id']}:{words[0]['word_id']}")
        await handle_teacher_lesson_callback(toggle_update, self.context)
        self.assertIn("Выбрано: 1 из 3", toggle_update.callback_query.edits[-1][0])
        self.assertIn("☑ receipt", toggle_update.callback_query.edits[-1][0])

        untoggle_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX}{lesson['id']}:{words[0]['word_id']}")
        await handle_teacher_lesson_callback(untoggle_update, self.context)
        self.assertIn("Выбрано: 0 из 3", untoggle_update.callback_query.edits[-1][0])
        self.assertIn("☐ receipt", untoggle_update.callback_query.edits[-1][0])

        all_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_ALL_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(all_update, self.context)
        self.assertIn("Выбрано: 3 из 3", all_update.callback_query.edits[-1][0])

        clear_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_CLEAR_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(clear_update, self.context)
        self.assertIn("Выбрано: 0 из 3", clear_update.callback_query.edits[-1][0])

        self.context.user_data["selected_lesson_words"] = {lesson["id"]: {words[0]["word_id"]}}
        done_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_DONE_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(done_update, self.context)
        self.assertIn("📖 Words", done_update.callback_query.edits[-1][0])
        self.assertNotIn("— выбор", done_update.callback_query.edits[-1][0])
        self.assertNotIn(lesson["id"], self.context.user_data.get("selected_lesson_words", {}))

    async def test_selection_ignores_missing_word_and_student_cannot_access(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 26 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        self.context.user_data["selected_lesson_words"] = {lesson["id"]: {999}}

        update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(update, self.context)
        self.assertIn("Выбрано: 0 из 1", update.callback_query.edits[-1][0])
        self.assertEqual(self.context.user_data["selected_lesson_words"][lesson["id"]], set())

        student_update = self._callback_update(f"{TEACHER_LESSON_WORDS_SELECT_PREFIX}{lesson['id']}", username="privetnormalno", user_id=103)
        await handle_teacher_lesson_callback(student_update, self.context)
        self.assertEqual(student_update.callback_query.edits, [])
        self.assertEqual(student_update.callback_query.message.replies, [])


    async def test_ai_translate_empty_selection_shows_message(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 27 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])

        update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(update, self.context)

        self.assertIn("Выберите хотя бы одно слово.", update.callback_query.edits[-1][0])
        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))

    async def test_ai_translate_success_preview_apply_and_cleanup(self) -> None:
        import app.handlers.teacher as teacher_module
        lesson = self.db.create_teacher_lesson("Lesson 28 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it"], self.teacher["id"])
        words = self.db.list_lesson_words(lesson["id"])
        self.context.user_data["selected_lesson_words"] = {lesson["id"]: {word["word_id"] for word in words}}
        calls = []

        async def fake_generate(english_words):
            calls.append(english_words)
            return [
                {"english": "receipt", "translation": "чек"},
                {"english": "worth it", "translation": "оно того стоит"},
            ]

        original = teacher_module.generate_word_translations
        teacher_module.generate_word_translations = fake_generate
        try:
            update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX}{lesson['id']}")
            await handle_teacher_lesson_callback(update, self.context)
        finally:
            teacher_module.generate_word_translations = original

        self.assertEqual(calls, [["receipt", "worth it"]])
        self.assertIn("Генерирую переводы...", update.callback_query.edits[0][0])
        self.assertIn("Будут обновлены переводы", update.callback_query.edits[-1][0])
        self.assertIn("1. receipt", update.callback_query.edits[-1][0])
        self.assertIn("2. worth it", update.callback_query.edits[-1][0])
        self.assertIn("→ чек", update.callback_query.edits[-1][0])
        buttons = [button.text for row in update.callback_query.edits[-1][1].inline_keyboard for button in row]
        self.assertIn("✏️ receipt", buttons)
        self.assertIn("✏️ worth it", buttons)
        self.assertEqual(self.db.get_lesson_word(lesson["id"], words[0]["word_id"])["translation"], "")
        self.assertIsNotNone(self.context.user_data.get("pending_ai_translation"))

        apply_update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_APPLY_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(apply_update, self.context)

        self.assertEqual(self.db.get_lesson_word(lesson["id"], words[0]["word_id"])["translation"], "чек")
        self.assertEqual(self.db.get_lesson_word(lesson["id"], words[1]["word_id"])["translation"], "оно того стоит")
        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))
        self.assertIn("📖 Words", apply_update.callback_query.edits[-1][0])

    async def test_ai_translate_invalid_json_fallback_does_not_save(self) -> None:
        import app.handlers.teacher as teacher_module
        lesson = self.db.create_teacher_lesson("Lesson 29 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]
        self.context.user_data["selected_lesson_words"] = {lesson["id"]: {word["word_id"]}}

        async def fake_generate(_english_words):
            return None

        original = teacher_module.generate_word_translations
        teacher_module.generate_word_translations = fake_generate
        try:
            update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX}{lesson['id']}")
            await handle_teacher_lesson_callback(update, self.context)
        finally:
            teacher_module.generate_word_translations = original

        self.assertIn("Не удалось получить перевод.", update.callback_query.edits[-1][0])
        self.assertEqual(self.db.get_lesson_word(lesson["id"], word["word_id"])["translation"], "")
        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))

    async def test_ai_translate_cancel_cleans_draft_keeps_selection_and_does_not_save(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 30 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]
        self.context.user_data["selected_lesson_words"] = {lesson["id"]: {word["word_id"]}}
        self.context.user_data["pending_ai_translation"] = {"lesson_id": lesson["id"], "translations": [{"word_id": word["word_id"], "english": "receipt", "translation": "чек"}]}

        update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(update, self.context)

        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))
        self.assertEqual(self.context.user_data["selected_lesson_words"][lesson["id"]], {word["word_id"]})
        self.assertEqual(self.db.get_lesson_word(lesson["id"], word["word_id"])["translation"], "")
        self.assertIn("Выбрано: 1 из 1", update.callback_query.edits[-1][0])


    async def test_ai_translation_preview_has_edit_buttons(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 32 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it"], self.teacher["id"])
        words = self.db.list_lesson_words(lesson["id"])
        self.context.user_data["pending_ai_translation"] = {
            "lesson_id": lesson["id"],
            "translations": [
                {"word_id": words[0]["word_id"], "english": "receipt", "translation": "чек"},
                {"word_id": words[1]["word_id"], "english": "worth it", "translation": "оно того стоит"},
            ],
        }

        update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_EDIT_PREFIX}{lesson['id']}:{words[0]['word_id']}")
        await handle_teacher_lesson_callback(update, self.context)

        self.assertIn("Введите новый перевод для:", update.callback_query.edits[-1][0])
        self.assertIn("receipt", update.callback_query.edits[-1][0])
        self.assertIn("Текущий перевод:\nчек", update.callback_query.edits[-1][0])

    async def test_ai_translation_edit_updates_draft_only_then_apply_saves_edit(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 33 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt", "worth it"], self.teacher["id"])
        words = self.db.list_lesson_words(lesson["id"])
        self.context.user_data["pending_ai_translation"] = {
            "lesson_id": lesson["id"],
            "translations": [
                {"word_id": words[0]["word_id"], "english": "receipt", "translation": "чек"},
                {"word_id": words[1]["word_id"], "english": "worth it", "translation": "оно того стоит"},
            ],
        }
        self.context.user_data["teacher_action"] = "edit_ai_translation_draft"
        self.context.user_data["pending_ai_translation_edit"] = {"lesson_id": lesson["id"], "word_id": words[0]["word_id"]}

        message_update = self._update(" кассовый чек ")
        self.assertTrue(await handle_teacher_message(message_update, self.context))

        self.assertEqual(self.context.user_data["pending_ai_translation"]["translations"][0]["translation"], "кассовый чек")
        self.assertEqual(self.db.get_lesson_word(lesson["id"], words[0]["word_id"])["translation"], "")
        self.assertIsNone(self.context.user_data.get("pending_ai_translation_edit"))
        self.assertIn("1. receipt", message_update.effective_message.replies[-1][0])
        self.assertIn("→ кассовый чек", message_update.effective_message.replies[-1][0])
        buttons = [button.text for row in message_update.effective_message.replies[-1][1].inline_keyboard for button in row]
        self.assertIn("✏️ receipt", buttons)

        apply_update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_APPLY_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(apply_update, self.context)

        self.assertEqual(self.db.get_lesson_word(lesson["id"], words[0]["word_id"])["translation"], "кассовый чек")
        self.assertEqual(self.db.get_lesson_word(lesson["id"], words[1]["word_id"])["translation"], "оно того стоит")
        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))
        self.assertIsNone(self.context.user_data.get("teacher_action"))

    async def test_ai_translation_cancel_cleans_edit_state_and_does_not_save_edit(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 34 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]
        self.context.user_data["selected_lesson_words"] = {lesson["id"]: {word["word_id"]}}
        self.context.user_data["pending_ai_translation"] = {"lesson_id": lesson["id"], "translations": [{"word_id": word["word_id"], "english": "receipt", "translation": "чек"}]}
        self.context.user_data["teacher_action"] = "edit_ai_translation_draft"
        self.context.user_data["pending_ai_translation_edit"] = {"lesson_id": lesson["id"], "word_id": word["word_id"]}

        update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX}{lesson['id']}")
        await handle_teacher_lesson_callback(update, self.context)

        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))
        self.assertIsNone(self.context.user_data.get("pending_ai_translation_edit"))
        self.assertIsNone(self.context.user_data.get("teacher_action"))
        self.assertEqual(self.db.get_lesson_word(lesson["id"], word["word_id"])["translation"], "")
        self.assertEqual(self.context.user_data["selected_lesson_words"][lesson["id"]], {word["word_id"]})

    async def test_ai_translation_missing_draft_and_item_fallbacks(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 35 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]

        missing_draft = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_EDIT_PREFIX}{lesson['id']}:{word['word_id']}")
        await handle_teacher_lesson_callback(missing_draft, self.context)
        self.assertIn("Draft не найден.", missing_draft.callback_query.edits[-1][0])
        self.assertIn("⬅️ Words", [button.text for row in missing_draft.callback_query.edits[-1][1].inline_keyboard for button in row])

        self.context.user_data["pending_ai_translation"] = {"lesson_id": lesson["id"], "translations": [{"word_id": word["word_id"], "english": "receipt", "translation": "чек"}]}
        missing_item = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_EDIT_PREFIX}{lesson['id']}:999")
        await handle_teacher_lesson_callback(missing_item, self.context)
        self.assertIn("Draft item не найден.", missing_item.callback_query.edits[-1][0])
        self.assertIn("⬅️ К preview", [button.text for row in missing_item.callback_query.edits[-1][1].inline_keyboard for button in row])

    async def test_ai_translation_edit_validation_max_length(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 36 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]
        self.context.user_data["pending_ai_translation"] = {"lesson_id": lesson["id"], "translations": [{"word_id": word["word_id"], "english": "receipt", "translation": "чек"}]}
        self.context.user_data["teacher_action"] = "edit_ai_translation_draft"
        self.context.user_data["pending_ai_translation_edit"] = {"lesson_id": lesson["id"], "word_id": word["word_id"]}

        update = self._update("x" * 501)
        self.assertTrue(await handle_teacher_message(update, self.context))

        self.assertIn("Максимум 500 символов.", update.effective_message.replies[-1][0])
        self.assertEqual(self.context.user_data["pending_ai_translation"]["translations"][0]["translation"], "чек")

    async def test_student_cannot_access_ai_translation_edit_callback_or_message(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 37 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        word = self.db.list_lesson_words(lesson["id"])[0]
        update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_EDIT_PREFIX}{lesson['id']}:{word['word_id']}", username="privetnormalno", user_id=103)

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
        self.assertEqual(update.callback_query.message.replies, [])

    async def test_student_cannot_access_ai_translation_callbacks(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 31 — Food", self.teacher["id"])
        self.db.add_lesson_words(lesson["id"], ["receipt"], self.teacher["id"])
        update = self._callback_update(f"{TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX}{lesson['id']}", username="privetnormalno", user_id=103)

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
        self.assertEqual(update.callback_query.message.replies, [])
        self.assertIsNone(self.context.user_data.get("pending_ai_translation"))

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

class AIWordTranslationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_word_translations_rejects_invalid_json(self) -> None:
        import os
        from unittest.mock import patch
        from app.ai.service import generate_word_translations

        class FakeProvider:
            async def generate_word_translations(self, *, words):
                return "not json"

        with patch.dict(os.environ, {"AI_PROVIDER": "polza"}), patch("app.ai.service.PolzaAIProvider", return_value=FakeProvider()):
            self.assertIsNone(await generate_word_translations(["receipt"]))

    async def test_generate_word_translations_rejects_missing_items(self) -> None:
        import os
        from unittest.mock import patch
        from app.ai.service import generate_word_translations

        class FakeProvider:
            async def generate_word_translations(self, *, words):
                return '[{"english":"receipt","translation":"чек"}]'

        with patch.dict(os.environ, {"AI_PROVIDER": "polza"}), patch("app.ai.service.PolzaAIProvider", return_value=FakeProvider()):
            self.assertIsNone(await generate_word_translations(["receipt", "worth it"]))

class LessonAssignmentCallbackTests(TeacherStudentAccessTests):
    async def test_missing_student_validation(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        update = self._callback_update(f"{TEACHER_LESSON_ASSIGN_STUDENT_PREFIX}{lesson['id']}:missingstudent")

        await handle_teacher_lesson_callback(update, self.context)

        self.assertIn("Ученик недоступен.", update.callback_query.edits[-1][0])
        self.assertIsNone(self.db.get_active_lesson_assignment(lesson["id"]))

    async def test_student_access_deny_for_assignment_callback(self) -> None:
        lesson = self.db.create_teacher_lesson("Lesson 15 — Food", self.teacher["id"])
        update = self._callback_update(f"{TEACHER_LESSON_ASSIGN_PREFIX}{lesson['id']}", username="privetnormalno", user_id=103)

        await handle_teacher_lesson_callback(update, self.context)

        self.assertEqual(update.callback_query.edits, [])
