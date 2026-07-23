import unittest
import uuid
from datetime import datetime, timezone

from app.ai.lesson_draft_dto import (
    GeneratedExerciseDraft,
    GeneratedGrammarDraft,
    GeneratedLessonDraft,
    GeneratedWordDraft,
    LessonDraftGenerationMetadata,
)
from app.ai.lesson_draft_editor import (
    DraftEditError,
    DraftEditIndexError,
    add_word,
    delete_word,
    update_word_field,
)


def _metadata() -> LessonDraftGenerationMetadata:
    return LessonDraftGenerationMetadata(
        generation_id=uuid.uuid4(),
        provider="polza",
        model="deepseek/deepseek-v4-flash",
        prompt_version=1,
        generated_at=datetime.now(timezone.utc),
    )


def _draft(words=2) -> GeneratedLessonDraft:
    metadata = _metadata()
    return GeneratedLessonDraft(
        topic="Present Simple: daily routines",
        level="A2",
        words=tuple(
            GeneratedWordDraft(source=f"word{i}", translation=f"слово{i}", example=f"Example {i}.")
            for i in range(words)
        ),
        grammar=(GeneratedGrammarDraft(title="Rule", explanation="Explanation.", example=None),),
        exercises=(
            GeneratedExerciseDraft(
                prompt="Choose the correct option.",
                options=("A", "B", "C"),
                correct_option_index=0,
                explanation=None,
            ),
        ),
        metadata=metadata,
    )


class UpdateWordFieldTests(unittest.TestCase):
    def test_updates_source(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 0, "source", "apple")
        self.assertEqual(updated.words[0].source, "apple")
        self.assertEqual(updated.words[0].translation, draft.words[0].translation)
        self.assertEqual(draft.words[0].source, "word0")

    def test_updates_translation(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 1, "translation", "яблоко")
        self.assertEqual(updated.words[1].translation, "яблоко")
        self.assertEqual(draft.words[1].translation, "слово1")

    def test_updates_example(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 0, "example", "New example.")
        self.assertEqual(updated.words[0].example, "New example.")

    def test_example_can_be_cleared_to_none(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 0, "example", "   ")
        self.assertIsNone(updated.words[0].example)

    def test_trims_whitespace(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 0, "source", "  apple  ")
        self.assertEqual(updated.words[0].source, "apple")

    def test_blank_required_field_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            update_word_field(draft, 0, "source", "   ")
        with self.assertRaises(DraftEditError):
            update_word_field(draft, 0, "translation", "")

    def test_source_and_translation_cannot_match(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            update_word_field(draft, 0, "translation", "word0")

    def test_duplicate_source_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            update_word_field(draft, 0, "source", "WORD1")

    def test_source_kept_same_case_insensitive_does_not_conflict_with_itself(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 0, "source", "WORD0")
        self.assertEqual(updated.words[0].source, "WORD0")

    def test_invalid_field_name_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(ValueError):
            update_word_field(draft, 0, "unknown", "value")

    def test_invalid_index_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditIndexError):
            update_word_field(draft, 99, "source", "apple")
        with self.assertRaises(DraftEditIndexError):
            update_word_field(draft, -1, "source", "apple")

    def test_source_over_max_length_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            update_word_field(draft, 0, "source", "a" * 101)

    def test_validation_failure_does_not_mutate_source_draft(self) -> None:
        draft = _draft()
        original_words = draft.words
        with self.assertRaises(DraftEditError):
            update_word_field(draft, 0, "source", "")
        self.assertEqual(draft.words, original_words)
        self.assertEqual(draft.words[0].source, "word0")

    def test_metadata_and_other_sections_unchanged(self) -> None:
        draft = _draft()
        updated = update_word_field(draft, 0, "source", "apple")
        self.assertIs(updated.metadata, draft.metadata)
        self.assertEqual(updated.grammar, draft.grammar)
        self.assertEqual(updated.exercises, draft.exercises)
        self.assertEqual(updated.topic, draft.topic)
        self.assertEqual(updated.level, draft.level)


class AddWordTests(unittest.TestCase):
    def test_appends_new_word(self) -> None:
        draft = _draft()
        updated = add_word(draft, source="cat", translation="кот", example="A cat.")
        self.assertEqual(len(updated.words), 3)
        self.assertEqual(updated.words[-1].source, "cat")
        self.assertEqual(updated.words[-1].translation, "кот")
        self.assertEqual(updated.words[-1].example, "A cat.")
        self.assertEqual(len(draft.words), 2)

    def test_example_is_optional(self) -> None:
        draft = _draft()
        updated = add_word(draft, source="cat", translation="кот")
        self.assertIsNone(updated.words[-1].example)

    def test_blank_source_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            add_word(draft, source="  ", translation="кот")

    def test_blank_translation_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            add_word(draft, source="cat", translation="")

    def test_duplicate_source_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            add_word(draft, source="WORD0", translation="новое")

    def test_source_equals_translation_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditError):
            add_word(draft, source="cat", translation="cat")

    def test_validation_failure_does_not_mutate_source_draft(self) -> None:
        draft = _draft()
        original_words = draft.words
        with self.assertRaises(DraftEditError):
            add_word(draft, source="", translation="кот")
        self.assertEqual(draft.words, original_words)

    def test_metadata_and_generation_id_unchanged(self) -> None:
        draft = _draft()
        updated = add_word(draft, source="cat", translation="кот")
        self.assertIs(updated.metadata, draft.metadata)
        self.assertEqual(updated.metadata.generation_id, draft.metadata.generation_id)


class DeleteWordTests(unittest.TestCase):
    def test_removes_word_and_shifts_indexes(self) -> None:
        draft = _draft(words=3)
        updated = delete_word(draft, 0)
        self.assertEqual(len(updated.words), 2)
        self.assertEqual(updated.words[0].source, "word1")
        self.assertEqual(updated.words[1].source, "word2")
        self.assertEqual(len(draft.words), 3)

    def test_invalid_index_rejected(self) -> None:
        draft = _draft()
        with self.assertRaises(DraftEditIndexError):
            delete_word(draft, 99)
        with self.assertRaises(DraftEditIndexError):
            delete_word(draft, -1)

    def test_metadata_and_generation_id_unchanged(self) -> None:
        draft = _draft()
        updated = delete_word(draft, 0)
        self.assertIs(updated.metadata, draft.metadata)
        self.assertEqual(updated.metadata.generation_id, draft.metadata.generation_id)

    def test_source_draft_not_mutated(self) -> None:
        draft = _draft(words=3)
        original_words = draft.words
        delete_word(draft, 1)
        self.assertEqual(draft.words, original_words)


if __name__ == "__main__":
    unittest.main()
