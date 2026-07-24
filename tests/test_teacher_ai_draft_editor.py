import unittest
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.ai.lesson_draft_dto import (
    GeneratedExerciseDraft,
    GeneratedGrammarDraft,
    GeneratedLessonDraft,
    GeneratedWordDraft,
    LessonDraftGenerationMetadata,
)
from app.database import Database
from app.handlers import teacher_ai_draft as ai_draft_module
from app.handlers.teacher_ai_draft import (
    TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX,
    TEACHER_AI_DRAFT_EXERCISES_PREFIX,
    TEACHER_AI_DRAFT_GRAMMAR_PREFIX,
    TEACHER_AI_DRAFT_LEVEL_PREFIX,
    TEACHER_AI_DRAFT_READY_PREFIX,
    TEACHER_AI_DRAFT_REGENERATE_PREFIX,
    TEACHER_AI_DRAFT_SAVE_PREFIX,
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
    teacher_usernames: frozenset = frozenset({"romateaches", "annateaches"})


def _sample_metadata() -> LessonDraftGenerationMetadata:
    return LessonDraftGenerationMetadata(
        generation_id=uuid.uuid4(),
        provider="polza",
        model="deepseek/deepseek-v4-flash",
        prompt_version=1,
        generated_at=datetime.now(timezone.utc),
    )


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
        metadata=_sample_metadata(),
    )


class TeacherAIDraftEditorTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(101, "romateaches", "Roma")
        self.other_teacher = self.db.upsert_user(102, "annateaches", "Anna")
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

    def _revision(self, lesson_id: int) -> str:
        state = ai_draft_module._get_state(self.context, lesson_id)
        return state["draft_revision"]

    def _field_code(self, field: str) -> str:
        return ai_draft_module._WORD_FIELD_CODES[field]

    async def _reach_ready_screen(self, draft: GeneratedLessonDraft, lesson_id: int | None = None):
        lesson_id = lesson_id or self.lesson["id"]
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}"), self.context)
        if ai_draft_module._get_state(self.context, lesson_id) is None:
            await handle_teacher_ai_draft_callback(
                self._callback_update(f"{TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX}{lesson_id}"), self.context
            )
        await handle_teacher_ai_draft_message(self._text_update("Present Simple: daily routines"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_LEVEL_PREFIX}{lesson_id}:A2"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_WORDS_PREFIX}{lesson_id}:5"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_GRAMMAR_PREFIX}{lesson_id}:1"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EXERCISES_PREFIX}{lesson_id}:3"), self.context)
        return await self._generate(draft, lesson_id)

    async def _generate(self, draft: GeneratedLessonDraft, lesson_id: int):
        """Runs a (re)generation using TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX. Only
        valid once the wizard params (topic/level/counts) are already set on state."""
        async def fake_generate(request):
            return draft

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            generate_update = self._callback_update(f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(generate_update, self.context)
            return generate_update
        finally:
            ai_draft_module.generate_lesson_draft = original

    async def _regenerate(self, draft: GeneratedLessonDraft, lesson_id: int):
        """Replaces the current draft via TEACHER_AI_DRAFT_REGENERATE_PREFIX (🔄
        Сгенерировать заново from the ready screen) — the other code path, besides
        the initial generation, that assigns a new draft_revision."""
        async def fake_generate(request):
            return draft

        original = ai_draft_module.generate_lesson_draft
        ai_draft_module.generate_lesson_draft = fake_generate
        try:
            regenerate_update = self._callback_update(f"{TEACHER_AI_DRAFT_REGENERATE_PREFIX}{lesson_id}")
            await handle_teacher_ai_draft_callback(regenerate_update, self.context)
            return regenerate_update
        finally:
            ai_draft_module.generate_lesson_draft = original

    async def _open_editor(self, draft: GeneratedLessonDraft, lesson_id: int | None = None):
        lesson_id = lesson_id or self.lesson["id"]
        await self._reach_ready_screen(draft, lesson_id)
        revision = self._revision(lesson_id)
        open_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX}{lesson_id}:{revision}")
        await handle_teacher_ai_draft_callback(open_update, self.context)
        return open_update


class ReadyScreenAndOverviewTests(TeacherAIDraftEditorTestCase):
    async def test_edit_button_appears_on_ready_screen(self) -> None:
        draft = _sample_draft()
        generate_update = await self._reach_ready_screen(draft)
        markup = generate_update.callback_query.edits[-1][1]
        self.assertIn("✏️ Редактировать", str(markup))

    async def test_editor_overview_shows_real_counts(self) -> None:
        draft = _sample_draft(words=3, grammar=2, exercises=4)
        open_update = await self._open_editor(draft)
        text, markup = open_update.callback_query.edits[-1]
        self.assertIn("Слова: 3", text)
        self.assertIn("Грамматика: 2", text)
        self.assertIn("Упражнения: 4", text)
        self.assertIn("📝 Слова — 3", str(markup))
        self.assertIn("📚 Грамматика — 2", str(markup))
        self.assertIn("🧩 Упражнения — 4", str(markup))

    async def test_grammar_and_exercises_buttons_show_unavailable_toast(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft()
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX}{lesson_id}:{revision}:grammar")
        await handle_teacher_ai_draft_callback(update, self.context)
        self.assertTrue(update.callback_query.alerts)
        self.assertEqual(update.callback_query.edits, [])

    async def test_unavailable_toast_blocked_on_stale_revision(self) -> None:
        lesson_id = self.lesson["id"]
        draft_a = _sample_draft()
        await self._open_editor(draft_a, lesson_id)
        stale_revision = self._revision(lesson_id)
        await self._regenerate(_sample_draft(words=3), lesson_id)

        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX}{lesson_id}:{stale_revision}:grammar")
        await handle_teacher_ai_draft_callback(update, self.context)
        self.assertEqual(update.callback_query.alerts, [])
        text, _ = update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)


class WordsListTests(TeacherAIDraftEditorTestCase):
    async def test_words_list_uses_correct_lesson_id(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(update, self.context)
        _, markup = update.callback_query.edits[-1]
        self.assertIn("1. word0 — слово0", str(markup))

    async def test_pagination_first_page_has_no_prev(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=12)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(update, self.context)
        markup_str = str(update.callback_query.edits[-1][1])
        self.assertNotIn("text='⬅️'", markup_str)
        self.assertIn("text='➡️'", markup_str)

    async def test_pagination_last_page_has_no_next(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=12)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        last_page = (12 + ai_draft_module._WORDS_PER_PAGE - 1) // ai_draft_module._WORDS_PER_PAGE - 1
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX}{lesson_id}:{revision}:{last_page}")
        await handle_teacher_ai_draft_callback(update, self.context)
        markup_str = str(update.callback_query.edits[-1][1])
        self.assertIn("text='⬅️'", markup_str)
        self.assertNotIn("text='➡️'", markup_str)

    async def test_out_of_range_page_is_clamped(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX}{lesson_id}:{revision}:99")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertIn("Страница 1 из 1", text)


class WordDetailAndEditTests(TeacherAIDraftEditorTestCase):
    async def test_word_details_show_current_values(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertIn("word0", text)
        self.assertIn("слово0", text)
        self.assertIn("Example 0.", text)

    async def test_invalid_word_index_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision}:99")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertIn("Слова", text)  # falls back to the words list

    async def test_edit_source_updates_only_that_word(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        edit_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:0:{self._field_code('source')}")
        await handle_teacher_ai_draft_callback(edit_update, self.context)
        self.assertEqual(self.context.user_data.get("teacher_action"), ai_draft_module._TEACHER_ACTION_EDITOR_INPUT)

        text_update = self._text_update("apple")
        handled = await handle_teacher_ai_draft_message(text_update, self.context)
        self.assertTrue(handled)
        reply_text, _ = text_update.effective_message.replies[-1]
        self.assertIn("apple", reply_text)

        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(state["draft"].words[0].source, "apple")
        self.assertEqual(state["draft"].words[1].source, "word1")
        self.assertNotIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)
        self.assertIsNone(self.context.user_data.get("teacher_action"))

    async def test_edit_translation_updates_only_that_word(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(
            self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:1:{self._field_code('translation')}"), self.context
        )
        await handle_teacher_ai_draft_message(self._text_update("яблоко"), self.context)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(state["draft"].words[1].translation, "яблоко")
        self.assertEqual(state["draft"].words[0].translation, "слово0")

    async def test_edit_example_updates_only_that_word(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(
            self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:0:{self._field_code('example')}"), self.context
        )
        await handle_teacher_ai_draft_message(self._text_update("A brand new example."), self.context)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(state["draft"].words[0].example, "A brand new example.")

    async def test_edit_field_validation_error_keeps_pending_state(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(
            self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:0:{self._field_code('source')}"), self.context
        )
        blank_update = self._text_update("   ")
        handled = await handle_teacher_ai_draft_message(blank_update, self.context)
        self.assertTrue(handled)
        self.assertEqual(self.context.user_data.get("teacher_action"), ai_draft_module._TEACHER_ACTION_EDITOR_INPUT)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(state["draft"].words[0].source, "word0")

    async def test_edit_field_invalid_index_in_callback_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:99:{self._field_code('source')}")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

    async def test_cancel_input_clears_pending_and_returns_to_word_detail(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(
            self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:0:{self._field_code('source')}"), self.context
        )
        cancel_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX}{lesson_id}:{revision}")
        await handle_teacher_ai_draft_callback(cancel_update, self.context)
        self.assertNotIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)
        self.assertIsNone(self.context.user_data.get("teacher_action"))
        text, _ = cancel_update.callback_query.edits[-1]
        self.assertIn("word0", text)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(state["draft"].words[0].source, "word0")

    async def test_several_manual_edits_keep_same_revision_and_buttons_keep_working(self) -> None:
        """Requirement: manual editing of the same draft must not rotate the
        revision, so buttons already shown to the teacher for the current
        revision keep working across several edits in a row."""
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision_before = self._revision(lesson_id)

        for field, value in (("source", "apple"), ("translation", "яблоко"), ("example", "An apple a day.")):
            update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision_before}:0:{self._field_code(field)}")
            await handle_teacher_ai_draft_callback(update, self.context)
            await handle_teacher_ai_draft_message(self._text_update(value), self.context)
            self.assertEqual(self._revision(lesson_id), revision_before)

        # The very button shown before any of the edits above should still work.
        detail_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision_before}:0")
        await handle_teacher_ai_draft_callback(detail_update, self.context)
        text, _ = detail_update.callback_query.edits[-1]
        self.assertIn("apple", text)
        self.assertIn("яблоко", text)
        self.assertNotEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)


class AddWordFlowTests(TeacherAIDraftEditorTestCase):
    async def test_add_word_flow_creates_valid_word(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX}{lesson_id}:{revision}"), self.context)
        await handle_teacher_ai_draft_message(self._text_update("cat"), self.context)
        await handle_teacher_ai_draft_message(self._text_update("кот"), self.context)
        await handle_teacher_ai_draft_message(self._text_update("A cat sleeps."), self.context)

        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 2)
        self.assertEqual(state["draft"].words[1].source, "cat")
        self.assertEqual(state["draft"].words[1].translation, "кот")
        self.assertEqual(state["draft"].words[1].example, "A cat sleeps.")
        self.assertNotIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)
        self.assertEqual(state["draft_revision"], revision)

    async def test_add_word_example_can_be_skipped(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX}{lesson_id}:{revision}"), self.context)
        await handle_teacher_ai_draft_message(self._text_update("dog"), self.context)
        await handle_teacher_ai_draft_message(self._text_update("собака"), self.context)
        await handle_teacher_ai_draft_message(self._text_update("-"), self.context)

        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertIsNone(state["draft"].words[1].example)

    async def test_add_word_blank_source_is_rejected_and_step_repeats(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX}{lesson_id}:{revision}"), self.context)
        blank_update = self._text_update("   ")
        await handle_teacher_ai_draft_message(blank_update, self.context)
        pending = self.context.user_data[ai_draft_module._PENDING_EDITOR_KEY]
        self.assertEqual(pending["step"], "source")
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 1)

    async def test_add_word_on_stale_revision_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        draft_a = _sample_draft(words=1)
        await self._open_editor(draft_a, lesson_id)
        stale_revision = self._revision(lesson_id)
        await self._regenerate(_sample_draft(words=1), lesson_id)

        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX}{lesson_id}:{stale_revision}")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)
        self.assertNotIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)


class DeleteWordFlowTests(TeacherAIDraftEditorTestCase):
    async def test_delete_requires_confirmation_screen(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, markup = update.callback_query.edits[-1]
        self.assertIn("Удалить слово", text)
        self.assertIn("Да, удалить", str(markup))
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 2)

    async def test_delete_cancellation_preserves_word(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX}{lesson_id}:{revision}:0"), self.context)
        cancel_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(cancel_update, self.context)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 2)
        self.assertEqual(state["draft"].words[0].source, "word0")

    async def test_delete_confirm_removes_word_and_updates_counts(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertIn("удалено", text)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 1)
        self.assertEqual(state["draft"].words[0].source, "word1")
        self.assertEqual(state["draft"].metadata.generation_id, draft.metadata.generation_id)
        self.assertEqual(state["draft_revision"], revision)

    async def test_delete_confirm_invalid_index_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX}{lesson_id}:{revision}:99")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)


class StaleAndSafetyTests(TeacherAIDraftEditorTestCase):
    async def test_missing_draft_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX}{lesson_id}:anyrev123")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

    async def test_editor_callbacks_after_regeneration_are_stale_safe(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        open_update = await self._open_editor(draft)
        revision = self._revision(lesson_id)
        words_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(words_update, self.context)

        ai_draft_module._clear_state(self.context, lesson_id)

        stale_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(stale_update, self.context)
        text, _ = stale_update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

    async def test_lesson_a_draft_not_accessible_via_lesson_b_callback(self) -> None:
        lesson_a = self.lesson["id"]
        lesson_b = self.db.create_teacher_lesson("Lesson 2 — Travel", self.teacher["id"])["id"]
        draft_a = _sample_draft(words=2)
        draft_b = _sample_draft(words=1)
        await self._open_editor(draft_a, lesson_a)
        await self._open_editor(draft_b, lesson_b)
        revision_a = self._revision(lesson_a)

        # Forged callback: lesson_b's id paired with lesson_a's (foreign) revision.
        cross_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX}{lesson_b}:{revision_a}:0")
        await handle_teacher_ai_draft_callback(cross_update, self.context)
        text, _ = cross_update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

        state_a = ai_draft_module._get_state(self.context, lesson_a)
        state_b = ai_draft_module._get_state(self.context, lesson_b)
        self.assertEqual(len(state_a["draft"].words), 2)
        self.assertEqual(len(state_b["draft"].words), 1)

    async def test_revision_for_lesson_a_does_not_affect_lesson_b(self) -> None:
        lesson_a = self.lesson["id"]
        lesson_b = self.db.create_teacher_lesson("Lesson 2 — Travel", self.teacher["id"])["id"]
        draft_a = _sample_draft(words=1)
        draft_b = _sample_draft(words=1)
        await self._open_editor(draft_a, lesson_a)
        await self._open_editor(draft_b, lesson_b)

        revision_a_before = self._revision(lesson_a)
        revision_b = self._revision(lesson_b)
        self.assertNotEqual(revision_a_before, revision_b)

        # Regenerating lesson A must not change lesson B's revision or its draft.
        await self._regenerate(_sample_draft(words=3), lesson_a)
        self.assertEqual(self._revision(lesson_b), revision_b)
        state_b = ai_draft_module._get_state(self.context, lesson_b)
        self.assertEqual(len(state_b["draft"].words), 1)

        # Lesson B's (still-current) buttons keep working, targeting only lesson B.
        detail_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_b}:{revision_b}:0")
        await handle_teacher_ai_draft_callback(detail_update, self.context)
        text, _ = detail_update.callback_query.edits[-1]
        self.assertNotEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

    async def test_pending_edit_for_lesson_a_still_targets_lesson_a_after_viewing_lesson_b(self) -> None:
        lesson_a = self.lesson["id"]
        lesson_b = self.db.create_teacher_lesson("Lesson 2 — Travel", self.teacher["id"])["id"]
        draft_a = _sample_draft(words=1)
        draft_b = _sample_draft(words=1)
        await self._open_editor(draft_a, lesson_a)
        revision_a = self._revision(lesson_a)
        await handle_teacher_ai_draft_callback(
            self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_a}:{revision_a}:0:{self._field_code('source')}"), self.context
        )
        pending = self.context.user_data[ai_draft_module._PENDING_EDITOR_KEY]
        self.assertEqual(pending["lesson_id"], lesson_a)
        self.assertEqual(pending["revision"], revision_a)

        # Seed lesson B's draft directly (bypassing the wizard, which would
        # itself overwrite the shared "teacher_action" flag) so this isolates
        # exactly one thing: does a pending edit ever leak across lesson_id.
        ai_draft_module._drafts(self.context)[lesson_b] = {
            "topic": "Travel", "level": "A2", "words_count": 1, "grammar_count": 1,
            "exercises_count": 1, "in_progress": False, "draft": draft_b,
            "draft_revision": ai_draft_module._generate_draft_revision(), "request": None,
        }
        revision_b = self._revision(lesson_b)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX}{lesson_b}:{revision_b}"), self.context)

        await handle_teacher_ai_draft_message(self._text_update("apple"), self.context)
        state_a = ai_draft_module._get_state(self.context, lesson_a)
        state_b = ai_draft_module._get_state(self.context, lesson_b)
        self.assertEqual(state_a["draft"].words[0].source, "apple")
        self.assertEqual(state_b["draft"].words[0].source, "word0")

    async def test_non_teacher_cannot_open_editor(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft()
        await self._reach_ready_screen(draft)
        revision = self._revision(lesson_id)
        update = self._callback_update(
            f"{TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX}{lesson_id}:{revision}", username="privetnormalno", user_id=103
        )
        await handle_teacher_ai_draft_callback(update, self.context)
        self.assertEqual(update.callback_query.edits, [])

    async def test_non_draft_lesson_blocks_editor(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1)
        await self._open_editor(draft, lesson_id)
        revision = self._revision(lesson_id)
        self.db.execute("UPDATE lessons SET status = ? WHERE id = ?", ("PUBLISHED", lesson_id))

        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX}{lesson_id}:{revision}")
        await handle_teacher_ai_draft_callback(update, self.context)
        text, _ = update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

    async def test_malformed_callback_data_is_ignored(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1)
        await self._open_editor(draft)
        # Missing the revision field entirely (pre-fix callback shape).
        update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX}{lesson_id}:0")
        await handle_teacher_ai_draft_callback(update, self.context)
        self.assertEqual(update.callback_query.edits, [])


class StaleRevisionCoreScenarioTests(TeacherAIDraftEditorTestCase):
    """The exact regression scenario from the follow-up report: Draft A's word-detail
    button must not be able to edit or delete an item in Draft B after a regenerate."""

    async def test_old_edit_button_after_regenerate_shows_stale_and_does_not_touch_draft_b(self) -> None:
        lesson_id = self.lesson["id"]
        draft_a = _sample_draft(words=2)
        await self._open_editor(draft_a, lesson_id)
        revision_a = self._revision(lesson_id)

        # 1-2: open Draft A's word card and keep the (now old) edit button's callback data.
        detail_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision_a}:0")
        await handle_teacher_ai_draft_callback(detail_update, self.context)
        old_edit_callback = f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision_a}:0:{self._field_code('source')}"
        old_delete_callback = f"{TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX}{lesson_id}:{revision_a}:0"

        # 3: regenerate -> Draft B replaces Draft A for the same lesson_id.
        draft_b = _sample_draft(words=5)
        await self._regenerate(draft_b, lesson_id)
        revision_b = self._revision(lesson_id)
        self.assertNotEqual(revision_a, revision_b)

        # 4-6: the stale edit button must be rejected and Draft B untouched.
        edit_update = self._callback_update(old_edit_callback)
        await handle_teacher_ai_draft_callback(edit_update, self.context)
        text, _ = edit_update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)

        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 5)
        self.assertEqual(state["draft"].words[0].source, draft_b.words[0].source)
        self.assertNotIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)

        # The stale delete button must be equally rejected, and must not shrink Draft B.
        delete_update = self._callback_update(old_delete_callback)
        await handle_teacher_ai_draft_callback(delete_update, self.context)
        text, _ = delete_update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)
        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 5)

    async def test_pending_edit_started_before_regenerate_does_not_apply_to_draft_b(self) -> None:
        lesson_id = self.lesson["id"]
        draft_a = _sample_draft(words=2)
        await self._open_editor(draft_a, lesson_id)
        revision_a = self._revision(lesson_id)

        # 7: start a pending edit for Draft A's word 0.
        edit_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision_a}:0:{self._field_code('source')}")
        await handle_teacher_ai_draft_callback(edit_update, self.context)
        self.assertIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)

        # 8: successful regenerate replaces Draft A with Draft B for the same lesson_id.
        draft_b = _sample_draft(words=4)
        await self._regenerate(draft_b, lesson_id)
        revision_b = self._revision(lesson_id)
        self.assertNotEqual(revision_a, revision_b)

        # 9: send the text that would have completed the old edit.
        text_update = self._text_update("hijacked-value")
        handled = await handle_teacher_ai_draft_message(text_update, self.context)

        # 10: text is not applied to Draft B, pending is cleared, safe message shown.
        self.assertTrue(handled)
        reply_text, _ = text_update.effective_message.replies[-1]
        self.assertEqual(reply_text, ai_draft_module._EDITOR_STALE_MESSAGE)

        state = ai_draft_module._get_state(self.context, lesson_id)
        self.assertEqual(len(state["draft"].words), 4)
        for word in state["draft"].words:
            self.assertNotEqual(word.source, "hijacked-value")
        self.assertEqual(state["draft"].words[0].source, draft_b.words[0].source)
        self.assertNotIn(ai_draft_module._PENDING_EDITOR_KEY, self.context.user_data)
        self.assertIsNone(self.context.user_data.get("teacher_action"))


class SaveAfterEditIntegrationTests(TeacherAIDraftEditorTestCase):
    async def test_edited_word_visible_through_repository_after_save(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=2)
        await self._open_editor(draft, lesson_id)
        revision = self._revision(lesson_id)

        await handle_teacher_ai_draft_callback(
            self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX}{lesson_id}:{revision}:0:{self._field_code('translation')}"), self.context
        )
        await handle_teacher_ai_draft_message(self._text_update("яблоко"), self.context)

        save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(save_update, self.context)

        repository = LessonRepository(self.db)
        service = LessonService(repository)
        service.assign_lesson_to_student(lesson_id, "privetnormalno", self.teacher["id"])
        training_words = repository.list_lesson_training_words(lesson_id, self.student["id"])
        translations = {w["english"]: w["translation"] for w in training_words}
        self.assertEqual(translations["word0"], "яблоко")

    async def test_stale_editor_action_after_save_shows_safe_message(self) -> None:
        lesson_id = self.lesson["id"]
        draft = _sample_draft(words=1)
        await self._open_editor(draft, lesson_id)
        revision = self._revision(lesson_id)

        save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{lesson_id}")
        await handle_teacher_ai_draft_callback(save_update, self.context)

        stale_update = self._callback_update(f"{TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX}{lesson_id}:{revision}:0")
        await handle_teacher_ai_draft_callback(stale_update, self.context)
        text, _ = stale_update.callback_query.edits[-1]
        self.assertEqual(text, ai_draft_module._EDITOR_STALE_MESSAGE)


class CallbackDataByteLengthTests(TeacherAIDraftEditorTestCase):
    """Requirement: every editor callback_data string must fit Telegram's 64-byte
    limit, even with a realistically large lesson_id/index/page — checked here against
    the real screen-builder functions, not hand-computed strings."""

    async def test_all_editor_screens_stay_within_64_bytes_for_large_ids(self) -> None:
        # Deliberately generous: a lesson_id near a million rows, and a draft far
        # bigger than the ~30-item practical cap documented for AI-generated drafts.
        lesson_id = 999_999
        revision = ai_draft_module._generate_draft_revision()
        big_draft = _sample_draft(words=999)
        big_draft = big_draft.__class__(
            topic=big_draft.topic,
            level=big_draft.level,
            words=tuple(
                GeneratedWordDraft(source=f"word{i}", translation=f"слово{i}", example=f"Example {i}.")
                for i in range(999)
            ),
            grammar=big_draft.grammar,
            exercises=big_draft.exercises,
            metadata=big_draft.metadata,
        )

        def assert_all_within_limit(markup) -> None:
            for row in markup.inline_keyboard:
                for button in row:
                    encoded = button.callback_data.encode("utf-8")
                    self.assertLessEqual(len(encoded), 64, f"{button.callback_data!r} is {len(encoded)} bytes")

        _, overview_markup = ai_draft_module._editor_overview_screen(lesson_id, big_draft, revision)
        assert_all_within_limit(overview_markup)

        _, words_markup = ai_draft_module._words_list_screen(lesson_id, big_draft, page=99, revision=revision)
        assert_all_within_limit(words_markup)

        _, detail_markup = ai_draft_module._word_detail_screen(lesson_id, big_draft, 998, revision)
        assert_all_within_limit(detail_markup)

        _, confirm_markup = ai_draft_module._word_delete_confirm_screen(lesson_id, big_draft, 998, revision)
        assert_all_within_limit(confirm_markup)

        cancel_markup = ai_draft_module._editor_input_cancel_markup(lesson_id, revision)
        assert_all_within_limit(cancel_markup)

    async def test_callback_data_builder_rejects_oversized_data(self) -> None:
        with self.assertRaises(ValueError):
            ai_draft_module._editor_callback_data("teacher:ai_draft:editor_word_delete_confirm:", "9" * 40, "x" * 40, "9" * 10)


if __name__ == "__main__":
    unittest.main()
