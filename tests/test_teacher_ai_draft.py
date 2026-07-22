import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.ai.lesson_draft_dto import (
    DraftGenerationError,
    DraftResponseValidationError,
    GeneratedExerciseDraft,
    GeneratedGrammarDraft,
    GeneratedLessonDraft,
    GeneratedWordDraft,
)
from app.database import Database
from app.handlers import teacher_ai_draft as ai_draft_module
from app.handlers.teacher import TEACHER_LESSON_AI_PREFIX, handle_teacher_lesson_callback
from app.handlers.teacher_ai_draft import (
    TEACHER_AI_DRAFT_CANCEL_PREFIX,
    TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX,
    TEACHER_AI_DRAFT_EDIT_PREFIX,
    TEACHER_AI_DRAFT_EXERCISES_PREFIX,
    TEACHER_AI_DRAFT_GRAMMAR_PREFIX,
    TEACHER_AI_DRAFT_LEVEL_PREFIX,
    TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX,
    TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX,
    TEACHER_AI_DRAFT_READY_PREFIX,
    TEACHER_AI_DRAFT_REGENERATE_PREFIX,
    TEACHER_AI_DRAFT_START_PREFIX,
    TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX,
    TEACHER_AI_DRAFT_WORDS_PREFIX,
    handle_teacher_ai_draft_callback,
    handle_teacher_ai_draft_message,
)
from app.lesson_repository import LessonRepository
from app.lesson_service import LessonService


@dataclass(frozen=True)
class RoleSettings:
    allowed_usernames: frozenset = frozenset({"privetnormalno"})
    admin_usernames: frozenset = frozenset({"wp_bvv"})
    teacher_usernames: frozenset = frozenset({"romateaches"})


def _sample_draft(words=2, grammar=1, exercises=1) -> GeneratedLessonDraft:
    return GeneratedLessonDraft(
        topic="Present Simple: daily routines",
        level="A2",
        words=tuple(
            GeneratedWordDraft(source=f"word{i}", translation=f"слово{i}", example=f"Example {i}.")
            for i in range(words)
        ),
        grammar=tuple(
            GeneratedGrammarDraft(title=f"Rule {i}", explanation=f"Explanation {i}.", example=None)
            for i in range(grammar)
        ),
        exercises=tuple(
            GeneratedExerciseDraft(
                prompt=f"Choose the correct option {i}.",
                options=("A", "B", "C"),
                correct_option_index=0,
                explanation=None,
            )
            for i in range(exercises)
        ),
    )


class TeacherAIDraftTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(101, "romateaches", "Roma")
        self.student = self.db.upsert_user(103, "privetnormalno", "Student")
        self.context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"db": self.db, "settings": RoleSettings()}),
            user_data={},
        )
        self.lesson = self.db.create_teacher_lesson("Lesson 1 — Food", self.teacher["id"])

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def _callback_update(self, data: str, *, username: str = "romateaches", user_id: int = 101):
        message = SimpleNamespace(replies=[])

        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))

        message.reply_text = reply_text
        query = SimpleNamespace(data=data, message=message, edits=[], answered=False, alerts=[])

        async def answer(text=None, show_alert=False):
            query.answered = True
            if text:
                query.alerts.append(text)

        async def edit_message_text(text, reply_markup=None):
            query.edits.append((text, reply_markup))

        query.answer = answer
        query.edit_message_text = edit_message_text
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, username=username),
            effective_message=message,
            callback_query=query,
        )

    def _text_update(self, text: str, *, username: str = "romateaches", user_id: int = 101):
        message = SimpleNamespace(text=text, replies=[])

        async def reply_text(reply, reply_markup=None):
            message.replies.append((reply, reply_markup))

        message.reply_text = reply_text
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, username=username),
            effective_message=message,
            callback_query=None,
        )

    def _lesson_service(self) -> LessonService:
        return LessonService(LessonRepository(self.db))

    async def _advance_through_wizard(self, *, level="A2", words="5", grammar="1", exercises="3"):
        lesson_id = self.lesson["id"]
        start = self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(start, self.context)

        topic_update = self._text_update("Present Simple: daily routines")
        await handle_teacher_ai_draft_message(topic_update, self.context)

        level_update = self._callback_update(f"{TEACHER_AI_DRAFT_LEVEL_PREFIX}{lesson_id}:{level}")
        await handle_teacher_ai_draft_callback(level_update, self.context)

        words_update = self._callback_update(f"{TEACHER_AI_DRAFT_WORDS_PREFIX}{lesson_id}:{words}")
        await handle_teacher_ai_draft_callback(words_update, self.context)

        grammar_update = self._callback_update(f"{TEACHER_AI_DRAFT_GRAMMAR_PREFIX}{lesson_id}:{grammar}")
        await handle_teacher_ai_draft_callback(grammar_update, self.context)

        exercises_update = self._callback_update(f"{TEACHER_AI_DRAFT_EXERCISES_PREFIX}{lesson_id}:{exercises}")
        await handle_teacher_ai_draft_callback(exercises_update, self.context)
        return exercises_update


class EntryScreenTests(TeacherAIDraftTestCase):
    async def test_entry_screen_shown_for_draft_lesson(self) -> None:
        update = self._callback_update(f"{TEACHER_LESSON_AI_PREFIX}{self.lesson['id']}")
        await handle_teacher_lesson_callback(update, self.context)
        self.assertIn("✨ Создать контент с AI", str(update.callback_query.edits[-1][1]))

    async def test_non_teacher_denied(self) -> None:
        update = self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{self.lesson['id']}", username="privetnormalno", user_id=103)
        await handle_teacher_ai_draft_callback(update, self.context)
        self.assertEqual(update.callback_query.edits, [])


class WizardFlowTests(TeacherAIDraftTestCase):
    async def test_full_wizard_reaches_confirmation_screen(self) -> None:
        exercises_update = await self._advance_through_wizard()
        text = exercises_update.callback_query.edits[-1][0]
        self.assertIn("✨ Генерация черновика", text)
        self.assertIn("Тема: Present Simple: daily routines", text)
        self.assertIn("Уровень: A2", text)
        self.assertIn("Слова: 5", text)
        self.assertIn("Грамматика: 1", text)
        self.assertIn("Упражнения: 3", text)

    async def test_invalid_topic_is_rejected_and_state_kept(self) -> None:
        lesson_id = self.lesson["id"]
        start = self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(start, self.context)

        bad_topic = self._text_update("ab")
        handled = await handle_teacher_ai_draft_message(bad_topic, self.context)
        self.assertTrue(handled)
        self.assertIn("тема", bad_topic.effective_message.replies[-1][0].lower())
        self.assertEqual(self.context.user_data.get("teacher_action"), ai_draft_module._TEACHER_ACTION_TOPIC)

    async def test_forged_level_value_is_rejected(self) -> None:
        lesson_id = self.lesson["id"]
        start = self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(start, self.context)
        await handle_teacher_ai_draft_message(self._text_update("Travel vocabulary"), self.context)

        forged = self._callback_update(f"{TEACHER_AI_DRAFT_LEVEL_PREFIX}{lesson_id}:C9")
        await handle_teacher_ai_draft_callback(forged, self.context)
        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertIsNone(state["level"])

    async def test_forged_words_count_is_rejected(self) -> None:
        lesson_id = self.lesson["id"]
        start = self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(start, self.context)
        await handle_teacher_ai_draft_message(self._text_update("Travel vocabulary"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_LEVEL_PREFIX}{lesson_id}:A2"), self.context)

        forged = self._callback_update(f"{ai_draft_module.TEACHER_AI_DRAFT_WORDS_PREFIX}{lesson_id}:999")
        await handle_teacher_ai_draft_callback(forged, self.context)
        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertIsNone(state["words_count"])

    async def test_edit_button_resets_wizard(self) -> None:
        await self._advance_through_wizard()
        lesson_id = self.lesson["id"]
        edit_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDIT_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(edit_update, self.context)
        self.assertIn("Введите тему урока", edit_update.callback_query.edits[-1][0])
        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertIsNone(state["topic"])
        self.assertIsNone(state["level"])

    async def test_cancel_clears_state(self) -> None:
        await self._advance_through_wizard()
        lesson_id = self.lesson["id"]
        cancel_update = self._callback_update(f"{TEACHER_AI_DRAFT_CANCEL_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(cancel_update, self.context)
        self.assertNotIn(ai_draft_module._STATE_KEY, self.context.user_data)
        self.assertNotIn("teacher_action", self.context.user_data)

    async def test_existing_content_warning_shown_and_continue_proceeds(self) -> None:
        lesson_id = self.lesson["id"]
        self._lesson_service().add_lesson_words(lesson_id, ["cat"], self.teacher["id"])

        start = self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(start, self.context)
        self.assertIn("В уроке уже есть контент", start.callback_query.edits[-1][0])

        cont = self._callback_update(f"{TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(cont, self.context)
        self.assertIn("Введите тему урока", cont.callback_query.edits[-1][0])


class GenerationTests(TeacherAIDraftTestCase):
    async def test_successful_generation_shows_ready_screen_and_does_not_touch_db(self) -> None:
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()

        draft = _sample_draft()

        async def fake_generate(request):
            return draft

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        text = generate_update.callback_query.edits[-1][0]
        self.assertIn("✨ Черновик готов", text)
        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertIs(state["draft"], draft)
        self.assertFalse(state["in_progress"])

        summary = self._lesson_service().get_lesson_summary(lesson_id)
        self.assertEqual(summary["words_count"], 0)
        self.assertEqual(summary["grammar_count"], 0)
        self.assertEqual(summary["exercises_count"], 0)

    async def test_network_error_shows_safe_message_with_retry(self) -> None:
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()

        async def fake_generate(request):
            raise DraftGenerationError("boom: secret-token-xyz")

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        text = generate_update.callback_query.edits[-1][0]
        self.assertEqual(text, "Не удалось получить ответ от AI-сервиса. Попробуйте ещё раз немного позже.")
        self.assertNotIn("secret-token-xyz", text)
        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertFalse(state["in_progress"])

    async def test_invalid_draft_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()

        async def fake_generate(request):
            raise DraftResponseValidationError("bad json content here")

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        text = generate_update.callback_query.edits[-1][0]
        self.assertEqual(text, "AI вернул некорректный черновик. Можно попробовать сгенерировать его ещё раз.")

    async def test_double_click_guard_blocks_concurrent_generation(self) -> None:
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()
        state = self.context.user_data[ai_draft_module._STATE_KEY]
        state["in_progress"] = True

        calls = []

        async def fake_generate(request):
            calls.append(request)
            return _sample_draft()

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        self.assertEqual(calls, [])
        self.assertEqual(generate_update.callback_query.edits, [])
        self.assertTrue(generate_update.callback_query.answered)

    async def test_retry_after_error_repeats_generation_with_same_params(self) -> None:
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()

        async def failing_generate(request):
            raise DraftGenerationError("boom")

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = failing_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        seen_requests = []
        draft = _sample_draft()

        async def succeeding_generate(request):
            seen_requests.append(request)
            return draft

        ai_draft_module.generate_lesson_draft = succeeding_generate
        try:
            retry_update = self._callback_update(f"{TEACHER_AI_DRAFT_REGENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(retry_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        self.assertEqual(len(seen_requests), 1)
        self.assertEqual(seen_requests[0].topic, "Present Simple: daily routines")
        self.assertIn("✨ Черновик готов", retry_update.callback_query.edits[-1][0])

    async def test_failed_regenerate_keeps_previous_draft(self) -> None:
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()

        good_draft = _sample_draft()

        async def succeed(request):
            return good_draft

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = succeed
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertIs(state["draft"], good_draft)

        async def fail(request):
            raise DraftGenerationError("boom")

        ai_draft_module.generate_lesson_draft = fail
        try:
            regenerate_update = self._callback_update(f"{TEACHER_AI_DRAFT_REGENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(regenerate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

        state = self.context.user_data[ai_draft_module._STATE_KEY]
        self.assertIs(state["draft"], good_draft)
        text = regenerate_update.callback_query.edits[-1][0]
        self.assertEqual(text, "Не удалось получить ответ от AI-сервиса. Попробуйте ещё раз немного позже.")

        show_current = self._callback_update(f"{TEACHER_AI_DRAFT_READY_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(show_current, self.context)
        self.assertIn("✨ Черновик готов", show_current.callback_query.edits[-1][0])


class PreviewTests(TeacherAIDraftTestCase):
    async def _generate_draft(self, draft):
        lesson_id = self.lesson["id"]
        await self._advance_through_wizard()

        async def fake_generate(request):
            return draft

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
        finally:
            ai_draft_module.generate_lesson_draft = original

    async def test_preview_menu_and_word_pagination(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=7, grammar=1, exercises=1)
        await self._generate_draft(draft)

        open_preview = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(open_preview, self.context)
        self.assertIn("Выберите раздел", open_preview.callback_query.edits[-1][0])

        page0 = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:words:0")
        await handle_teacher_ai_draft_callback(page0, self.context)
        text0 = page0.callback_query.edits[-1][0]
        self.assertIn("word0", text0)
        self.assertIn("word4", text0)
        self.assertNotIn("word5", text0)
        self.assertIn("Страница 1 из 2", text0)

        page1 = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:words:1")
        await handle_teacher_ai_draft_callback(page1, self.context)
        text1 = page1.callback_query.edits[-1][0]
        self.assertIn("word5", text1)
        self.assertIn("word6", text1)
        self.assertIn("Страница 2 из 2", text1)

    async def test_grammar_and_exercise_pagination_show_correct_answer(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1, grammar=2, exercises=2)
        await self._generate_draft(draft)

        grammar_page = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:grammar:0")
        await handle_teacher_ai_draft_callback(grammar_page, self.context)
        self.assertIn("Rule 0", grammar_page.callback_query.edits[-1][0])
        self.assertNotIn("Rule 1", grammar_page.callback_query.edits[-1][0])

        exercise_page = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:exercises:0")
        await handle_teacher_ai_draft_callback(exercise_page, self.context)
        text = exercise_page.callback_query.edits[-1][0]
        self.assertIn("✅ A", text)

    async def test_stale_draft_shows_lost_message(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft()
        await self._generate_draft(draft)

        self.context.user_data.pop(ai_draft_module._STATE_KEY, None)

        open_preview = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(open_preview, self.context)
        self.assertIn("Черновик больше недоступен", open_preview.callback_query.edits[-1][0])

    async def test_callback_for_different_lesson_is_rejected(self) -> None:
        other_lesson = self.db.create_teacher_lesson("Lesson 2 — Travel", self.teacher["id"])
        draft = _sample_draft()
        await self._generate_draft(draft)

        mismatched = self._callback_update(f"{TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX}{other_lesson['id']}")
        await handle_teacher_ai_draft_callback(mismatched, self.context)
        self.assertIn("Черновик больше недоступен", mismatched.callback_query.edits[-1][0])


if __name__ == "__main__":
    unittest.main()
