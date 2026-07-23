import json
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

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
    TEACHER_AI_DRAFT_EXERCISES_PREFIX,
    TEACHER_AI_DRAFT_GRAMMAR_PREFIX,
    TEACHER_AI_DRAFT_LEVEL_PREFIX,
    TEACHER_AI_DRAFT_SAVE_PREFIX,
    TEACHER_AI_DRAFT_START_PREFIX,
    TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX,
    TEACHER_AI_DRAFT_WORDS_PREFIX,
    handle_teacher_ai_draft_callback,
    handle_teacher_ai_draft_message,
)
from app.lesson_repository import LessonRepository
from app.lesson_runtime import LessonRuntimeService, LessonSection
from app.lesson_service import DraftAlreadySavedError, DraftSaveConflictError, ExerciseItemError, LessonService


def _sample_metadata(generation_id: uuid.UUID | None = None) -> LessonDraftGenerationMetadata:
    return LessonDraftGenerationMetadata(
        generation_id=generation_id or uuid.uuid4(),
        provider="polza",
        model="deepseek/deepseek-v4-flash",
        prompt_version=1,
        generated_at=datetime.now(timezone.utc),
    )


def _sample_draft(*, words=2, grammar=1, exercises=1, generation_id: uuid.UUID | None = None) -> GeneratedLessonDraft:
    return GeneratedLessonDraft(
        topic="Present Simple: daily routines",
        level="A2",
        words=tuple(
            GeneratedWordDraft(source=f"word{i}", translation=f"слово{i}", example=f"Example {i}.")
            for i in range(words)
        ),
        grammar=tuple(
            GeneratedGrammarDraft(title=f"Rule {i}", explanation=f"Explanation {i}.", example=f"Grammar example {i}.")
            for i in range(grammar)
        ),
        exercises=tuple(
            GeneratedExerciseDraft(
                prompt=f"Choose the correct option {i}.",
                options=("A", "B", "C"),
                correct_option_index=1,
                explanation=f"Because B is right {i}.",
            )
            for i in range(exercises)
        ),
        metadata=_sample_metadata(generation_id),
    )


class SaveGeneratedDraftDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(1, "teacher", "Teacher")
        self.lesson = self.db.create_teacher_lesson("Lesson 1 — Food", self.teacher["id"])

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_saves_full_draft(self) -> None:
        result = self.db.save_generated_draft(
            self.lesson["id"],
            generation_id="gen-1",
            owner_user_id=self.teacher["id"],
            words=[("cat", "кот", "A cat sleeps.")],
            grammar=[("Present Simple", "Explanation text", "Example text")],
            exercises=[("Pick one", json.dumps(["A", "B", "C"]), 1, "Because B")],
        )
        self.assertEqual(result, "saved")

    def test_word_translation_and_example_are_saved(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("cat", "кот", "A cat sleeps.")], grammar=[], exercises=[],
        )
        word = self.db.list_lesson_words(self.lesson["id"])[0]
        full = self.db.get_lesson_word(self.lesson["id"], word["word_id"])
        self.assertEqual(full["english"], "cat")
        self.assertEqual(full["translation"], "кот")
        self.assertEqual(full["example"], "A cat sleeps.")

    def test_grammar_fields_are_saved(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[], grammar=[("Present Simple", "Explanation text", "Example text")], exercises=[],
        )
        item = self.db.list_grammar_items(self.lesson["id"])[0]
        self.assertEqual(item["title"], "Present Simple")
        self.assertEqual(item["explanation"], "Explanation text")
        self.assertEqual(item["example"], "Example text")

    def test_exercise_fields_are_saved(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[], grammar=[], exercises=[("Pick one", json.dumps(["A", "B", "C"]), 1, "Because B")],
        )
        item = self.db.list_exercise_items(self.lesson["id"])[0]
        self.assertEqual(item["prompt"], "Pick one")
        self.assertEqual(json.loads(item["options_json"]), ["A", "B", "C"])
        self.assertEqual(item["correct_option_index"], 1)
        self.assertEqual(item["explanation"], "Because B")

    def test_counts_match_draft_after_save(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("a", "а", None), ("b", "б", None)],
            grammar=[("G1", "E1", None)],
            exercises=[("Q1", json.dumps(["A", "B"]), 0, None)],
        )
        summary = self.db.get_lesson_summary(self.lesson["id"])
        self.assertEqual(summary["words_count"], 2)
        self.assertEqual(summary["grammar_count"], 1)
        self.assertEqual(summary["exercises_count"], 1)

    def test_same_generation_id_cannot_be_saved_twice(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("a", "а", None)], grammar=[], exercises=[],
        )
        result = self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("b", "б", None)], grammar=[], exercises=[],
        )
        self.assertEqual(result, "already_saved")

    def test_repeat_save_does_not_create_duplicate_rows(self) -> None:
        for _ in range(2):
            self.db.save_generated_draft(
                self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
                words=[("a", "а", None)], grammar=[], exercises=[],
            )
        self.assertEqual(len(self.db.list_lesson_words(self.lesson["id"])), 1)

    def test_words_conflict_blocks_entire_save(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("a", "а", None)], grammar=[], exercises=[],
        )
        result = self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-2", owner_user_id=self.teacher["id"],
            words=[("b", "б", None)],
            grammar=[("G", "E", None)],
            exercises=[("Q", json.dumps(["A", "B"]), 0, None)],
        )
        self.assertEqual(result, "conflict")
        self.assertEqual(len(self.db.list_lesson_words(self.lesson["id"])), 1)
        self.assertEqual(len(self.db.list_grammar_items(self.lesson["id"])), 0)
        self.assertEqual(len(self.db.list_exercise_items(self.lesson["id"])), 0)

    def test_grammar_conflict_rolls_back_everything(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[], grammar=[("G", "E", None)], exercises=[],
        )
        result = self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-2", owner_user_id=self.teacher["id"],
            words=[("b", "б", None)],
            grammar=[("G2", "E2", None)],
            exercises=[("Q", json.dumps(["A", "B"]), 0, None)],
        )
        self.assertEqual(result, "conflict")
        self.assertEqual(len(self.db.list_lesson_words(self.lesson["id"])), 0)
        self.assertEqual(len(self.db.list_grammar_items(self.lesson["id"])), 1)
        self.assertEqual(len(self.db.list_exercise_items(self.lesson["id"])), 0)

    def test_exercises_conflict_rolls_back_everything(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[], grammar=[], exercises=[("Q", json.dumps(["A", "B"]), 0, None)],
        )
        result = self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-2", owner_user_id=self.teacher["id"],
            words=[("b", "б", None)],
            grammar=[("G2", "E2", None)],
            exercises=[("Q2", json.dumps(["A", "B"]), 0, None)],
        )
        self.assertEqual(result, "conflict")
        self.assertEqual(len(self.db.list_lesson_words(self.lesson["id"])), 0)
        self.assertEqual(len(self.db.list_grammar_items(self.lesson["id"])), 0)
        self.assertEqual(len(self.db.list_exercise_items(self.lesson["id"])), 1)

    def test_empty_draft_section_does_not_block_save(self) -> None:
        self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("a", "а", None)], grammar=[], exercises=[],
        )
        result = self.db.save_generated_draft(
            self.lesson["id"], generation_id="gen-2", owner_user_id=self.teacher["id"],
            words=[],  # empty: must not conflict even though words already exist
            grammar=[("G", "E", None)],
            exercises=[],
        )
        self.assertEqual(result, "saved")
        self.assertEqual(len(self.db.list_grammar_items(self.lesson["id"])), 1)

    def test_mid_transaction_failure_rolls_back_all_inserts(self) -> None:
        with self.assertRaises(Exception):
            self.db.save_generated_draft(
                self.lesson["id"], generation_id="gen-err", owner_user_id=self.teacher["id"],
                words=[("a", "а", None)],
                grammar=[],
                # options_json=None violates NOT NULL, forcing a failure after the word insert.
                exercises=[("Q", None, 0, None)],
            )
        self.assertEqual(len(self.db.list_lesson_words(self.lesson["id"])), 0)
        summary = self.db.get_lesson_summary(self.lesson["id"])
        self.assertIsNone(summary["ai_draft_generation_id"])

    def test_missing_lesson_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.db.save_generated_draft(
                999999, generation_id="gen-1", owner_user_id=self.teacher["id"],
                words=[("a", "а", None)], grammar=[], exercises=[],
            )


class SaveGeneratedDraftServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(1, "teacher", "Teacher")
        self.lesson = self.db.create_teacher_lesson("Lesson 1 — Food", self.teacher["id"])
        self.service = LessonService(LessonRepository(self.db))

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_successful_save_returns_summary_with_counts(self) -> None:
        summary = self.service.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("cat", "кот", None)],
            grammar=[("G", "E", None)],
            exercises=[("Q", ["A", "B"], 0, None)],
        )
        self.assertEqual(summary["words_count"], 1)
        self.assertEqual(summary["grammar_count"], 1)
        self.assertEqual(summary["exercises_count"], 1)

    def test_duplicate_generation_id_raises_already_saved(self) -> None:
        self.service.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("cat", "кот", None)], grammar=[], exercises=[],
        )
        with self.assertRaises(DraftAlreadySavedError):
            self.service.save_generated_draft(
                self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
                words=[("dog", "собака", None)], grammar=[], exercises=[],
            )

    def test_conflict_raises_conflict_error_with_exact_message(self) -> None:
        self.service.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("cat", "кот", None)], grammar=[], exercises=[],
        )
        with self.assertRaises(DraftSaveConflictError) as ctx:
            self.service.save_generated_draft(
                self.lesson["id"], generation_id="gen-2", owner_user_id=self.teacher["id"],
                words=[("dog", "собака", None)], grammar=[], exercises=[],
            )
        self.assertEqual(
            str(ctx.exception),
            "Не удалось сохранить черновик: один или несколько разделов урока уже содержат материалы. "
            "Чтобы не потерять ручные изменения, автоматическое объединение пока недоступно.",
        )

    def test_invalid_exercise_option_count_is_rejected(self) -> None:
        with self.assertRaises(ExerciseItemError):
            self.service.save_generated_draft(
                self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
                words=[], grammar=[], exercises=[("Q", ["only one"], 0, None)],
            )

    def test_invalid_correct_option_index_is_rejected(self) -> None:
        with self.assertRaises(ExerciseItemError):
            self.service.save_generated_draft(
                self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
                words=[], grammar=[], exercises=[("Q", ["A", "B"], 5, None)],
            )

    def test_missing_lesson_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_generated_draft(
                999999, generation_id="gen-1", owner_user_id=self.teacher["id"],
                words=[("a", "а", None)], grammar=[], exercises=[],
            )

    def test_blank_generation_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_generated_draft(
                self.lesson["id"], generation_id="   ", owner_user_id=self.teacher["id"],
                words=[("a", "а", None)], grammar=[], exercises=[],
            )


class SaveGeneratedDraftRuntimeIntegrationTests(unittest.TestCase):
    """Confirms saved AI content is indistinguishable from manually-added content
    to the same repository methods the student Lesson Runtime actually uses."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.db.init_schema()
        self.teacher = self.db.upsert_user(1, "teacher", "Teacher")
        self.student = self.db.upsert_user(2, "student", "Student")
        self.lesson = self.db.create_teacher_lesson("Lesson 1 — Food", self.teacher["id"])
        self.repository = LessonRepository(self.db)
        self.service = LessonService(self.repository)

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_saved_draft_is_visible_to_student_runtime(self) -> None:
        self.service.save_generated_draft(
            self.lesson["id"], generation_id="gen-1", owner_user_id=self.teacher["id"],
            words=[("cat", "кот", "A cat sleeps.")],
            grammar=[("Present Simple", "Explanation", None)],
            exercises=[("Pick one", ["A", "B", "C"], 1, "Because B")],
        )

        self.service.assign_lesson_to_student(self.lesson["id"], "student", self.teacher["id"])

        student_view = self.repository.get_student_lesson(self.lesson["id"], "student")
        self.assertIsNotNone(student_view)
        self.assertEqual(student_view["words_count"], 1)
        self.assertEqual(student_view["grammar_count"], 1)
        self.assertEqual(student_view["exercises_count"], 1)

        training_words = self.repository.list_lesson_training_words(self.lesson["id"], self.student["id"])
        self.assertEqual(len(training_words), 1)
        self.assertEqual(training_words[0]["english"], "cat")
        self.assertEqual(training_words[0]["translation"], "кот")

        grammar_items = self.repository.list_grammar_items(self.lesson["id"])
        self.assertEqual(grammar_items[0]["title"], "Present Simple")

        exercise_items = self.repository.list_exercise_items(self.lesson["id"])
        self.assertEqual(exercise_items[0]["correct_option_index"], 1)

        runtime = LessonRuntimeService(self.repository)
        next_section = runtime.get_next_section(self.lesson["id"], "student")
        self.assertEqual(next_section, LessonSection.WORDS)


class SaveGeneratedDraftHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class RoleSettings:
            allowed_usernames: frozenset = frozenset({"privetnormalno"})
            admin_usernames: frozenset = frozenset({"wp_bvv"})
            teacher_usernames: frozenset = frozenset({"romateaches"})

        self.RoleSettings = RoleSettings
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

    async def _reach_ready_screen(self, draft: GeneratedLessonDraft, lesson_id: int | None = None):
        lesson_id = lesson_id or self.lesson["id"]
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}"), self.context)
        if ai_draft_module._get_state(self.context, lesson_id) is None:
            # Lesson already had content, so START showed the existing-content
            # warning instead of beginning the wizard directly - continue past it.
            await handle_teacher_ai_draft_callback(
                self._callback_update(f"{TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX}{lesson_id}"), self.context
            )
        await handle_teacher_ai_draft_message(self._text_update("Present Simple: daily routines"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_LEVEL_PREFIX}{lesson_id}:A2"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_WORDS_PREFIX}{lesson_id}:5"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_GRAMMAR_PREFIX}{lesson_id}:1"), self.context)
        await handle_teacher_ai_draft_callback(self._callback_update(f"{TEACHER_AI_DRAFT_EXERCISES_PREFIX}{lesson_id}:3"), self.context)

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

    async def test_save_button_appears_after_successful_generation(self) -> None:
        draft = _sample_draft()
        generate_update = await self._reach_ready_screen(draft)
        markup = generate_update.callback_query.edits[-1][1]
        self.assertIn("✅ Сохранить в урок", str(markup))

    async def test_save_persists_via_lesson_service_and_shows_counts(self) -> None:
        draft = _sample_draft(words=3, grammar=1, exercises=2)
        await self._reach_ready_screen(draft)

        save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}")
        await handle_teacher_ai_draft_callback(save_update, self.context)

        text = save_update.callback_query.edits[-1][0]
        self.assertIn("✅ Материалы сохранены в урок", text)
        self.assertIn("📚 Слова: 3", text)
        self.assertIn("📘 Грамматика: 1", text)
        self.assertIn("📝 Упражнения: 2", text)

        service = LessonService(LessonRepository(self.db))
        summary = service.get_lesson_summary(self.lesson["id"])
        self.assertEqual(summary["words_count"], 3)
        self.assertEqual(summary["grammar_count"], 1)
        self.assertEqual(summary["exercises_count"], 2)

    async def test_save_uses_draft_scoped_to_correct_lesson(self) -> None:
        other_lesson = self.db.create_teacher_lesson("Lesson 2 — Travel", self.teacher["id"])
        draft_a = _sample_draft()
        await self._reach_ready_screen(draft_a, lesson_id=self.lesson["id"])

        # No draft was ever generated for other_lesson.
        save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{other_lesson['id']}")
        await handle_teacher_ai_draft_callback(save_update, self.context)
        self.assertIn("Черновик не найден или устарел", save_update.callback_query.edits[-1][0])

        service = LessonService(LessonRepository(self.db))
        self.assertEqual(service.get_lesson_summary(other_lesson["id"])["words_count"], 0)

    async def test_missing_draft_shows_clear_message(self) -> None:
        save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}")
        await handle_teacher_ai_draft_callback(save_update, self.context)
        self.assertIn("Черновик не найден или устарел. Сгенерируйте его заново.", save_update.callback_query.edits[-1][0])

    async def test_repeated_save_callback_does_not_duplicate(self) -> None:
        draft = _sample_draft(words=2, grammar=1, exercises=1)
        await self._reach_ready_screen(draft)

        first = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}")
        await handle_teacher_ai_draft_callback(first, self.context)
        self.assertIn("✅ Материалы сохранены", first.callback_query.edits[-1][0])

        # Simulate a duplicate/late-arriving Telegram update that still finds the
        # draft in state (e.g. it was already in flight before the first save
        # cleared it) - the persistent generation_id guard in SQLite must catch
        # this even when the Telegram-state-only guard would not.
        ai_draft_module._drafts(self.context)[self.lesson["id"]] = {
            "topic": draft.topic,
            "level": draft.level,
            "words_count": len(draft.words),
            "grammar_count": len(draft.grammar),
            "exercises_count": len(draft.exercises),
            "in_progress": False,
            "draft": draft,
            "request": None,
        }
        second = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}")
        await handle_teacher_ai_draft_callback(second, self.context)
        self.assertIn("уже был сохранён", second.callback_query.edits[-1][0])

        service = LessonService(LessonRepository(self.db))
        summary = service.get_lesson_summary(self.lesson["id"])
        self.assertEqual(summary["words_count"], 2)

    async def test_conflict_with_existing_content_shows_warning(self) -> None:
        service = LessonService(LessonRepository(self.db))
        service.add_lesson_words(self.lesson["id"], ["existing"], self.teacher["id"])

        draft = _sample_draft(words=2, grammar=0, exercises=0)
        await self._reach_ready_screen(draft)

        save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}")
        await handle_teacher_ai_draft_callback(save_update, self.context)
        text = save_update.callback_query.edits[-1][0]
        self.assertIn("уже содержат материалы", text)

        summary = service.get_lesson_summary(self.lesson["id"])
        self.assertEqual(summary["words_count"], 1)

    async def test_service_exception_shows_safe_message_and_logs(self) -> None:
        draft = _sample_draft()
        await self._reach_ready_screen(draft)

        with patch.object(LessonService, "save_generated_draft", side_effect=RuntimeError("boom: secret detail")):
            with self.assertLogs("app.handlers.teacher_ai_draft", level="ERROR"):
                save_update = self._callback_update(f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}")
                await handle_teacher_ai_draft_callback(save_update, self.context)

        text = save_update.callback_query.edits[-1][0]
        self.assertNotIn("boom", text)
        self.assertNotIn("secret detail", text)
        self.assertNotIn("Traceback", text)

    async def test_non_teacher_cannot_save_draft(self) -> None:
        draft = _sample_draft()
        await self._reach_ready_screen(draft)

        save_update = self._callback_update(
            f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{self.lesson['id']}", username="privetnormalno", user_id=103
        )
        await handle_teacher_ai_draft_callback(save_update, self.context)
        self.assertEqual(save_update.callback_query.edits, [])

        service = LessonService(LessonRepository(self.db))
        self.assertEqual(service.get_lesson_summary(self.lesson["id"])["words_count"], 0)


if __name__ == "__main__":
    unittest.main()
