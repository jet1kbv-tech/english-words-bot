"""AI Draft Generator v1: in-memory lesson content draft generation.

This module implements the teacher-facing wizard that collects generation
parameters (topic, level, counts), calls the AI generator service, and
lets the teacher preview, regenerate, and save the resulting draft. Until
saved, the draft lives only in `context.user_data` for the duration of the
Telegram session and never changes existing lesson content. Saving writes
into the same lesson tables the Lesson Runtime already reads (via
`LessonService`/`LessonRepository`), through one dedicated atomic
operation (`save_generated_draft`) rather than the manual per-item
add methods — see `LessonService.save_generated_draft` for the transaction
boundary. Editing an already-generated draft and merging into an
already-non-empty section remain out of scope.
"""

from __future__ import annotations

import logging
import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.ai.lesson_draft_dto import (
    ALLOWED_EXERCISES_COUNTS,
    ALLOWED_GRAMMAR_COUNTS,
    ALLOWED_LEVELS,
    ALLOWED_WORDS_COUNTS,
    DEFAULT_EXERCISES_COUNT,
    DEFAULT_GRAMMAR_COUNT,
    DEFAULT_WORDS_COUNT,
    DraftGenerationError,
    DraftRequestValidationError,
    DraftResponseParseError,
    DraftResponseValidationError,
    GeneratedLessonDraft,
    build_generation_request,
    validate_level,
    validate_topic,
)
from app.ai.lesson_draft_editor import (
    WORD_FIELDS,
    DraftEditError,
    DraftEditIndexError,
    add_word,
    delete_word,
    update_word_field,
)
from app.ai.lesson_draft_generator import generate_lesson_draft
from app.auth.roles import Role, RoleResolver
from app.database import Database
from app.lesson_metadata import lesson_display_name
from app.lesson_repository import LESSON_STATUS_DRAFT, LessonRepository
from app.lesson_service import DraftAlreadySavedError, DraftSaveConflictError, DraftSaveForbiddenError, LessonService

logger = logging.getLogger(__name__)

_STATE_KEY = "ai_lesson_drafts"
_ACTIVE_LESSON_KEY = "teacher_ai_draft_active_lesson_id"
_TEACHER_ACTION_TOPIC = "teacher_ai_draft_topic"
_TEACHER_ACTION_EDITOR_INPUT = "teacher_ai_draft_editor_input"
_PENDING_EDITOR_KEY = "ai_draft_editor_pending"

_NETWORK_ERROR_MESSAGE = "Не удалось получить ответ от AI-сервиса. Попробуйте ещё раз немного позже."
_INVALID_DRAFT_MESSAGE = "AI вернул некорректный черновик. Можно попробовать сгенерировать его ещё раз."
_DRAFT_LOST_MESSAGE = "Черновик больше недоступен. Сгенерируйте его заново."
_DRAFT_NOT_FOUND_FOR_SAVE_MESSAGE = "Черновик не найден или устарел. Сгенерируйте его заново."
_SAVE_ERROR_MESSAGE = "Не удалось сохранить черновик из-за внутренней ошибки. Попробуйте ещё раз немного позже."
_EDITOR_STALE_MESSAGE = "Этот черновик больше недоступен или был обновлён. Откройте урок и перейдите к актуальному черновику."
_EDITOR_UNAVAILABLE_MESSAGE = "Редактирование этого раздела появится в одном из следующих обновлений."

TEACHER_AI_DRAFT_START_PREFIX = "teacher:ai_draft:start:"
TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX = "teacher:ai_draft:warn_continue:"
TEACHER_AI_DRAFT_LEVEL_PREFIX = "teacher:ai_draft:level:"
TEACHER_AI_DRAFT_WORDS_PREFIX = "teacher:ai_draft:words:"
TEACHER_AI_DRAFT_GRAMMAR_PREFIX = "teacher:ai_draft:grammar:"
TEACHER_AI_DRAFT_EXERCISES_PREFIX = "teacher:ai_draft:exercises:"
TEACHER_AI_DRAFT_EDIT_PREFIX = "teacher:ai_draft:edit:"
TEACHER_AI_DRAFT_CANCEL_PREFIX = "teacher:ai_draft:cancel:"
TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX = "teacher:ai_draft:generate:"
TEACHER_AI_DRAFT_REGENERATE_PREFIX = "teacher:ai_draft:regenerate:"
TEACHER_AI_DRAFT_READY_PREFIX = "teacher:ai_draft:ready:"
TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX = "teacher:ai_draft:preview:"
TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX = "teacher:ai_draft:preview_section:"
TEACHER_AI_DRAFT_SAVE_PREFIX = "teacher:ai_draft:save:"

TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX = "teacher:ai_draft:editor:"
TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX = "teacher:ai_draft:editor_words:"
TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX = "teacher:ai_draft:editor_word:"
TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX = "teacher:ai_draft:editor_word_edit:"
TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX = "teacher:ai_draft:editor_word_delete:"
TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX = "teacher:ai_draft:editor_word_delete_confirm:"
TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX = "teacher:ai_draft:editor_word_add:"
TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX = "teacher:ai_draft:editor_cancel_input:"
TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX = "teacher:ai_draft:editor_unavailable:"

TEACHER_AI_DRAFT_CALLBACK_PREFIXES = (
    TEACHER_AI_DRAFT_START_PREFIX,
    TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX,
    TEACHER_AI_DRAFT_LEVEL_PREFIX,
    TEACHER_AI_DRAFT_WORDS_PREFIX,
    TEACHER_AI_DRAFT_GRAMMAR_PREFIX,
    TEACHER_AI_DRAFT_EXERCISES_PREFIX,
    TEACHER_AI_DRAFT_EDIT_PREFIX,
    TEACHER_AI_DRAFT_CANCEL_PREFIX,
    TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX,
    TEACHER_AI_DRAFT_REGENERATE_PREFIX,
    TEACHER_AI_DRAFT_READY_PREFIX,
    TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX,
    TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX,
    TEACHER_AI_DRAFT_SAVE_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX,
    TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX,
)

_WORDS_PER_PAGE = 5

_SECTION_LABELS = {
    "words": "📚 Слова",
    "grammar": "📘 Грамматика",
    "exercises": "📝 Упражнения",
}


def _lesson_service(db: Database) -> LessonService:
    return LessonService(LessonRepository(db))


def _is_admin_acting_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    settings = context.application.bot_data["settings"]
    db = context.application.bot_data.get("db")
    role = RoleResolver(settings, db).role_for(user.username)
    return role is Role.ADMIN


def _back_to_lesson_button(lesson_id: int) -> InlineKeyboardButton:
    from app.handlers.teacher import TEACHER_LESSON_BACK_PREFIX

    return InlineKeyboardButton("⬅️ К уроку", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")


def _cancel_button(lesson_id: int) -> InlineKeyboardButton:
    return InlineKeyboardButton("Отмена", callback_data=f"{TEACHER_AI_DRAFT_CANCEL_PREFIX}{lesson_id}")


def _parse_lesson_id(data: str, prefix: str) -> int | None:
    payload = data.removeprefix(prefix).strip()
    return int(payload) if payload.isdigit() else None


def _parse_lesson_and_value(data: str, prefix: str) -> tuple[int, str] | None:
    payload = data.removeprefix(prefix).strip()
    lesson_id_text, sep, value = payload.partition(":")
    if sep != ":" or not lesson_id_text.isdigit() or not value:
        return None
    return int(lesson_id_text), value


def _generate_draft_revision() -> str:
    """A short, URL-safe token identifying one in-memory draft "generation" for editor
    callback data — cheap to embed unlike the full `generation_id` UUID, and lets stale
    callbacks/pending input from a since-regenerated draft be detected and rejected."""
    return secrets.token_urlsafe(6)


def _editor_callback_data(prefix: str, *parts: object) -> str:
    data = prefix + ":".join(str(part) for part in parts)
    byte_length = len(data.encode("utf-8"))
    if byte_length > 64:
        raise ValueError(f"AI draft editor callback_data exceeds Telegram's 64-byte limit ({byte_length} bytes): {data!r}")
    return data


def _has_existing_content(summary) -> bool:
    return int(summary["words_count"] or 0) > 0 or int(summary["grammar_count"] or 0) > 0 or int(summary["exercises_count"] or 0) > 0


def _authorize(service: LessonService, lesson_id: int | None):
    if lesson_id is None:
        return None
    summary = service.get_lesson_summary(lesson_id)
    if summary is None or summary["status"] != LESSON_STATUS_DRAFT:
        return None
    return summary


def _drafts(context: ContextTypes.DEFAULT_TYPE) -> dict[int, dict]:
    return context.user_data.setdefault(_STATE_KEY, {})


def _get_state(context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> dict | None:
    return _drafts(context).get(lesson_id)


def _clear_pending_editor(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_PENDING_EDITOR_KEY, None)
    if context.user_data.get("teacher_action") == _TEACHER_ACTION_EDITOR_INPUT:
        context.user_data.pop("teacher_action", None)


def _clear_state(context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    _drafts(context).pop(lesson_id, None)
    if context.user_data.get(_ACTIVE_LESSON_KEY) == lesson_id:
        context.user_data.pop(_ACTIVE_LESSON_KEY, None)
        if context.user_data.get("teacher_action") == _TEACHER_ACTION_TOPIC:
            context.user_data.pop("teacher_action", None)
    pending = context.user_data.get(_PENDING_EDITOR_KEY)
    if pending is not None and pending.get("lesson_id") == lesson_id:
        _clear_pending_editor(context)


def _clear_stale_pending(context: ContextTypes.DEFAULT_TYPE, lesson_id: int | None, current_revision: str | None) -> None:
    """Clears pending editor state only if it belongs to this lesson_id and to a
    revision other than `current_revision` — i.e. only if it is actually stale."""
    pending = context.user_data.get(_PENDING_EDITOR_KEY)
    if pending is not None and pending.get("lesson_id") == lesson_id and pending.get("revision") != current_revision:
        _clear_pending_editor(context)


def _resolve_editor_action(
    context: ContextTypes.DEFAULT_TYPE, service: LessonService, lesson_id: int | None, revision: str
) -> GeneratedLessonDraft | None:
    """Resolves the draft for an editor callback, requiring both `lesson_id` and
    `revision` to match the current in-memory draft for that lesson. On any mismatch
    (missing/unauthorized lesson, or a revision from a since-regenerated draft), any
    pending editor state belonging to the stale revision is cleared and `None` is
    returned — callers must then show the existing safe "draft is stale" message
    without touching the draft."""
    summary = _authorize(service, lesson_id)
    state = _get_state(context, lesson_id) if lesson_id is not None else None
    draft = state.get("draft") if state is not None else None
    if summary is None or state is None or draft is None:
        _clear_stale_pending(context, lesson_id, None)
        return None
    current_revision = state.get("draft_revision")
    if current_revision != revision:
        _clear_stale_pending(context, lesson_id, current_revision)
        return None
    return draft


def _entry_screen(lesson_id: int, summary) -> tuple[str, InlineKeyboardMarkup]:
    if summary["status"] != LESSON_STATUS_DRAFT:
        text = "\n".join([
            "🤖 AI-помощник",
            "",
            "Генерация AI-черновика доступна только для урока в статусе DRAFT.",
        ])
        return text, InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]])
    text = "\n".join([
        "🤖 AI-помощник",
        "",
        "Здесь можно сгенерировать черновик содержимого урока с помощью AI: слова, грамматику и упражнения.",
        "",
        "Черновик создаётся отдельно и не сохраняется автоматически — сохранение появится на следующем этапе.",
        "",
        f"Урок: {lesson_display_name(summary)}",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Создать контент с AI", callback_data=f"{TEACHER_AI_DRAFT_START_PREFIX}{lesson_id}")],
        [_back_to_lesson_button(lesson_id)],
    ])
    return text, markup


async def show_ai_draft_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, summary, *, edit: bool = False) -> None:
    text, markup = _entry_screen(lesson_id, summary)
    query = update.callback_query
    if edit and query is not None:
        await query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=markup)


def _existing_content_warning_screen(lesson_id: int) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "В уроке уже есть контент.\n\n"
        "AI создаст отдельный черновик и не изменит существующие материалы.\n\n"
        "Сохранение и объединение будут добавлены на следующем этапе."
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Продолжить", callback_data=f"{TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX}{lesson_id}")],
        [_cancel_button(lesson_id)],
    ])
    return text, markup


def _topic_step_screen() -> str:
    return (
        "Введите тему урока.\n\n"
        "Например:\n"
        "Present Simple: daily routines\n"
        "Travel vocabulary\n"
        "Ordering food in a restaurant"
    )


def _level_step_screen(lesson_id: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = [
        [InlineKeyboardButton(level, callback_data=f"{TEACHER_AI_DRAFT_LEVEL_PREFIX}{lesson_id}:{level}")]
        for level in ALLOWED_LEVELS
    ]
    rows.append([_cancel_button(lesson_id)])
    return "Выберите уровень (CEFR):", InlineKeyboardMarkup(rows)


def _count_step_screen(lesson_id: int, prefix: str, allowed: tuple[int, ...], default: int, title: str) -> tuple[str, InlineKeyboardMarkup]:
    buttons = []
    for value in allowed:
        label = f"{value} (рекомендуется)" if value == default else str(value)
        buttons.append(InlineKeyboardButton(label, callback_data=f"{prefix}{lesson_id}:{value}"))
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([_cancel_button(lesson_id)])
    return title, InlineKeyboardMarkup(rows)


def _words_step_screen(lesson_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return _count_step_screen(
        lesson_id, TEACHER_AI_DRAFT_WORDS_PREFIX, ALLOWED_WORDS_COUNTS, DEFAULT_WORDS_COUNT, "Сколько слов сгенерировать?"
    )


def _grammar_step_screen(lesson_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return _count_step_screen(
        lesson_id, TEACHER_AI_DRAFT_GRAMMAR_PREFIX, ALLOWED_GRAMMAR_COUNTS, DEFAULT_GRAMMAR_COUNT, "Сколько грамматических карточек сгенерировать?"
    )


def _exercises_step_screen(lesson_id: int) -> tuple[str, InlineKeyboardMarkup]:
    return _count_step_screen(
        lesson_id, TEACHER_AI_DRAFT_EXERCISES_PREFIX, ALLOWED_EXERCISES_COUNTS, DEFAULT_EXERCISES_COUNT, "Сколько упражнений сгенерировать?"
    )


def _confirm_screen(lesson_id: int, summary, state: dict) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        "✨ Генерация черновика",
        "",
        f"Урок: {lesson_display_name(summary)}",
        f"Тема: {state['topic']}",
        f"Уровень: {state['level']}",
        f"Слова: {state['words_count']}",
        f"Грамматика: {state['grammar_count']}",
        f"Упражнения: {state['exercises_count']}",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Сгенерировать", callback_data=f"{TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("← Изменить", callback_data=f"{TEACHER_AI_DRAFT_EDIT_PREFIX}{lesson_id}")],
        [_cancel_button(lesson_id)],
    ])
    return text, markup


def _error_screen(lesson_id: int, message: str, *, has_previous_draft: bool) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[InlineKeyboardButton("🔄 Попробовать ещё раз", callback_data=f"{TEACHER_AI_DRAFT_REGENERATE_PREFIX}{lesson_id}")]]
    if has_previous_draft:
        rows.append([InlineKeyboardButton("👀 Текущий черновик", callback_data=f"{TEACHER_AI_DRAFT_READY_PREFIX}{lesson_id}")])
    rows.append([_cancel_button(lesson_id)])
    return message, InlineKeyboardMarkup(rows)


def _ready_screen(lesson_id: int, draft: GeneratedLessonDraft) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        "✨ Черновик готов",
        f"Тема: {draft.topic}",
        f"Уровень: {draft.level}",
        f"📚 Слова: {len(draft.words)}",
        f"📘 Грамматика: {len(draft.grammar)}",
        f"📝 Упражнения: {len(draft.exercises)}",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 Посмотреть", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"{TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("✅ Сохранить в урок", callback_data=f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("🔄 Сгенерировать заново", callback_data=f"{TEACHER_AI_DRAFT_REGENERATE_PREFIX}{lesson_id}")],
        [_cancel_button(lesson_id)],
    ])
    return text, markup


def _save_success_screen(lesson_id: int, summary) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        "✅ Материалы сохранены в урок",
        "",
        f"📚 Слова: {int(summary['words_count'] or 0)}",
        f"📘 Грамматика: {int(summary['grammar_count'] or 0)}",
        f"📝 Упражнения: {int(summary['exercises_count'] or 0)}",
    ])
    markup = InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]])
    return text, markup


def _preview_menu_screen(lesson_id: int, draft: GeneratedLessonDraft) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        "👀 Просмотр черновика",
        "",
        f"Тема: {draft.topic}",
        f"Уровень: {draft.level}",
        "",
        "Выберите раздел:",
    ])
    rows = []
    if draft.words:
        rows.append([InlineKeyboardButton(f"📚 Слова ({len(draft.words)})", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:words:0")])
    if draft.grammar:
        rows.append([InlineKeyboardButton(f"📘 Грамматика ({len(draft.grammar)})", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:grammar:0")])
    if draft.exercises:
        rows.append([InlineKeyboardButton(f"📝 Упражнения ({len(draft.exercises)})", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:exercises:0")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"{TEACHER_AI_DRAFT_READY_PREFIX}{lesson_id}")])
    rows.append([_cancel_button(lesson_id)])
    return text, InlineKeyboardMarkup(rows)


def _section_page_count(draft: GeneratedLessonDraft, section: str) -> int:
    if section == "words":
        return max(1, (len(draft.words) + _WORDS_PER_PAGE - 1) // _WORDS_PER_PAGE)
    if section == "grammar":
        return max(1, len(draft.grammar))
    if section == "exercises":
        return max(1, len(draft.exercises))
    return 0


def _format_words_page(draft: GeneratedLessonDraft, page: int) -> str:
    start = page * _WORDS_PER_PAGE
    items = draft.words[start:start + _WORDS_PER_PAGE]
    lines = [_SECTION_LABELS["words"], ""]
    for word in items:
        line = f"• {word.source} — {word.translation}"
        if word.example:
            line += f"\n  {word.example}"
        lines.append(line)
    return "\n".join(lines)


def _format_grammar_page(draft: GeneratedLessonDraft, page: int) -> str:
    item = draft.grammar[page]
    lines = [_SECTION_LABELS["grammar"], "", item.title, "", item.explanation]
    if item.example:
        lines.extend(["", item.example])
    return "\n".join(lines)


def _format_exercise_page(draft: GeneratedLessonDraft, page: int) -> str:
    item = draft.exercises[page]
    lines = [_SECTION_LABELS["exercises"], "", item.prompt, ""]
    for index, option in enumerate(item.options):
        marker = "✅" if index == item.correct_option_index else "▫️"
        lines.append(f"{marker} {option}")
    if item.explanation:
        lines.extend(["", item.explanation])
    return "\n".join(lines)


def _preview_section_screen(lesson_id: int, draft: GeneratedLessonDraft, section: str, page: int) -> tuple[str, InlineKeyboardMarkup] | None:
    total_pages = _section_page_count(draft, section)
    if section not in _SECTION_LABELS or not (0 <= page < total_pages):
        return None

    if section == "words":
        text = _format_words_page(draft, page)
    elif section == "grammar":
        text = _format_grammar_page(draft, page)
    else:
        text = _format_exercise_page(draft, page)

    text += f"\n\nСтраница {page + 1} из {total_pages}"

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:{section}:{page - 1}"))
    if page + 1 < total_pages:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX}{lesson_id}:{section}:{page + 1}"))

    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("⬅️ Разделы", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX}{lesson_id}")])
    rows.append([_cancel_button(lesson_id)])
    return text, InlineKeyboardMarkup(rows)


_WORD_FIELD_PROMPTS = {
    "source": "Введите новое слово:",
    "translation": "Введите новый перевод:",
    "example": "Введите новый пример.\nОтправьте «-», чтобы удалить пример.",
}

# Callback data is byte-constrained (Telegram's 64-byte callback_data limit), so word
# fields use a 1-char code on the wire instead of their full name.
_WORD_FIELD_CODES = {"source": "s", "translation": "t", "example": "e"}
_WORD_FIELD_CODES_REVERSE = {code: field for field, code in _WORD_FIELD_CODES.items()}
assert set(_WORD_FIELD_CODES) == set(WORD_FIELDS)


def _editor_overview_screen(lesson_id: int, draft: GeneratedLessonDraft, revision: str) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        "✏️ Редактирование черновика",
        "",
        f"Слова: {len(draft.words)}",
        f"Грамматика: {len(draft.grammar)}",
        f"Упражнения: {len(draft.exercises)}",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 Слова — {len(draft.words)}", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX, lesson_id, revision, 0))],
        [InlineKeyboardButton(f"📚 Грамматика — {len(draft.grammar)}", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX, lesson_id, revision, "grammar"))],
        [InlineKeyboardButton(f"🧩 Упражнения — {len(draft.exercises)}", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX, lesson_id, revision, "exercises"))],
        [InlineKeyboardButton("👀 Посмотреть весь черновик", callback_data=f"{TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("✅ Сохранить в урок", callback_data=f"{TEACHER_AI_DRAFT_SAVE_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{TEACHER_AI_DRAFT_READY_PREFIX}{lesson_id}")],
    ])
    return text, markup


def _words_list_screen(lesson_id: int, draft: GeneratedLessonDraft, page: int, revision: str) -> tuple[str, InlineKeyboardMarkup]:
    total = len(draft.words)
    total_pages = max(1, (total + _WORDS_PER_PAGE - 1) // _WORDS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _WORDS_PER_PAGE
    page_items = list(enumerate(draft.words))[start:start + _WORDS_PER_PAGE]

    lines = ["📝 Слова", ""]
    if not draft.words:
        lines.append("Слов пока нет.")
    else:
        lines.append(f"Страница {page + 1} из {total_pages}")
    text = "\n".join(lines)

    rows: list[list[InlineKeyboardButton]] = []
    for index, word in page_items:
        label = f"{index + 1}. {word.source} — {word.translation}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(label, callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX, lesson_id, revision, index))])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX, lesson_id, revision, page - 1)))
    if page + 1 < total_pages:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX, lesson_id, revision, page + 1)))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("➕ Добавить слово", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX, lesson_id, revision))])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX, lesson_id, revision))])
    return text, InlineKeyboardMarkup(rows)


def _word_detail_screen(lesson_id: int, draft: GeneratedLessonDraft, index: int, revision: str) -> tuple[str, InlineKeyboardMarkup] | None:
    if not (0 <= index < len(draft.words)):
        return None
    word = draft.words[index]
    text = "\n".join([
        f"📝 Слово {index + 1}",
        "",
        f"Слово: {word.source}",
        f"Перевод: {word.translation}",
        f"Пример: {word.example or '—'}",
    ])
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить слово", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX, lesson_id, revision, index, _WORD_FIELD_CODES["source"]))],
        [InlineKeyboardButton("✏️ Изменить перевод", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX, lesson_id, revision, index, _WORD_FIELD_CODES["translation"]))],
        [InlineKeyboardButton("✏️ Изменить пример", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX, lesson_id, revision, index, _WORD_FIELD_CODES["example"]))],
        [InlineKeyboardButton("🗑 Удалить", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX, lesson_id, revision, index))],
        [InlineKeyboardButton("⬅️ К списку", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX, lesson_id, revision, 0))],
    ])
    return text, markup


def _word_delete_confirm_screen(lesson_id: int, draft: GeneratedLessonDraft, index: int, revision: str) -> tuple[str, InlineKeyboardMarkup] | None:
    if not (0 <= index < len(draft.words)):
        return None
    word = draft.words[index]
    text = f"Удалить слово «{word.source} — {word.translation}»?"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Да, удалить", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX, lesson_id, revision, index))],
        [InlineKeyboardButton("⬅️ Отмена", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX, lesson_id, revision, index))],
    ])
    return text, markup


def _editor_input_cancel_markup(lesson_id: int, revision: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=_editor_callback_data(TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX, lesson_id, revision))]])


async def _begin_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    _drafts(context)[lesson_id] = {
        "topic": None,
        "level": None,
        "words_count": None,
        "grammar_count": None,
        "exercises_count": None,
        "in_progress": False,
        "draft": None,
        "draft_revision": None,
        "request": None,
    }
    context.user_data[_ACTIVE_LESSON_KEY] = lesson_id
    context.user_data["teacher_action"] = _TEACHER_ACTION_TOPIC
    query = update.callback_query
    if query is not None:
        await query.edit_message_text(_topic_step_screen(), reply_markup=InlineKeyboardMarkup([[_cancel_button(lesson_id)]]))


async def _run_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, state: dict) -> None:
    query = update.callback_query
    if state.get("in_progress"):
        if query is not None:
            await query.answer("Генерация уже выполняется, подождите…", show_alert=True)
        return

    state["in_progress"] = True
    if query is not None:
        await query.edit_message_text("✨ Генерирую черновик…")
    try:
        try:
            request = build_generation_request(
                lesson_id=lesson_id,
                topic=state["topic"],
                level=state["level"],
                words_count=state["words_count"],
                grammar_count=state["grammar_count"],
                exercises_count=state["exercises_count"],
            )
        except DraftRequestValidationError:
            logger.warning("Lesson draft generation request failed validation for lesson_id=%s", lesson_id)
            if query is not None:
                text, markup = _error_screen(lesson_id, _INVALID_DRAFT_MESSAGE, has_previous_draft=state.get("draft") is not None)
                await query.edit_message_text(text, reply_markup=markup)
            return

        try:
            draft = await generate_lesson_draft(request)
        except DraftGenerationError:
            if query is not None:
                text, markup = _error_screen(lesson_id, _NETWORK_ERROR_MESSAGE, has_previous_draft=state.get("draft") is not None)
                await query.edit_message_text(text, reply_markup=markup)
            return
        except (DraftResponseParseError, DraftResponseValidationError):
            if query is not None:
                text, markup = _error_screen(lesson_id, _INVALID_DRAFT_MESSAGE, has_previous_draft=state.get("draft") is not None)
                await query.edit_message_text(text, reply_markup=markup)
            return

        state["draft"] = draft
        state["draft_revision"] = _generate_draft_revision()
        state["request"] = request
        if query is not None:
            text, markup = _ready_screen(lesson_id, draft)
            await query.edit_message_text(text, reply_markup=markup)
    finally:
        state["in_progress"] = False


async def _save_draft_to_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, state: dict, summary) -> None:
    query = update.callback_query
    draft: GeneratedLessonDraft | None = state.get("draft")
    if draft is None:
        if query is not None:
            await query.edit_message_text(
                _DRAFT_NOT_FOUND_FOR_SAVE_MESSAGE,
                reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]),
            )
        return

    from app.handlers.teacher import _teacher_user_id

    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)
    owner_user_id = _teacher_user_id(update, db)
    is_admin = _is_admin_acting_user(update, context)
    required_teacher_user_id = None if is_admin else owner_user_id

    if not is_admin and (owner_user_id is None or summary["teacher_user_id"] != owner_user_id):
        logger.info("Lesson draft save forbidden: acting user does not own lesson (lesson_id=%s)", lesson_id)
        if query is not None:
            await query.edit_message_text(
                "У вас нет прав на изменение этого урока.",
                reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]),
            )
        return

    words = [(word.source, word.translation, word.example) for word in draft.words]
    grammar = [(item.title, item.explanation, item.example) for item in draft.grammar]
    exercises = [(item.prompt, list(item.options), item.correct_option_index, item.explanation) for item in draft.exercises]
    generation_id = str(draft.metadata.generation_id)

    try:
        saved_summary = service.save_generated_draft(
            lesson_id,
            generation_id=generation_id,
            owner_user_id=owner_user_id,
            words=words,
            grammar=grammar,
            exercises=exercises,
            required_teacher_user_id=required_teacher_user_id,
        )
    except DraftAlreadySavedError:
        logger.info("Lesson draft already saved (lesson_id=%s, generation_id=%s)", lesson_id, generation_id)
        _drafts(context).pop(lesson_id, None)
        pending = context.user_data.get(_PENDING_EDITOR_KEY)
        if pending is not None and pending.get("lesson_id") == lesson_id:
            _clear_pending_editor(context)
        if query is not None:
            await query.edit_message_text(
                "Этот черновик уже был сохранён в урок.",
                reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]),
            )
        return
    except DraftSaveConflictError as exc:
        logger.info("Lesson draft save conflict (lesson_id=%s, generation_id=%s)", lesson_id, generation_id)
        if query is not None:
            await query.edit_message_text(str(exc), reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
        return
    except DraftSaveForbiddenError as exc:
        logger.info("Lesson draft save forbidden by service (lesson_id=%s, generation_id=%s)", lesson_id, generation_id)
        if query is not None:
            await query.edit_message_text(str(exc), reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
        return
    except Exception:
        logger.exception("Lesson draft save failed (lesson_id=%s, generation_id=%s)", lesson_id, generation_id)
        if query is not None:
            await query.edit_message_text(_SAVE_ERROR_MESSAGE, reply_markup=InlineKeyboardMarkup([[_cancel_button(lesson_id)]]))
        return

    logger.info(
        "Lesson draft saved (lesson_id=%s, generation_id=%s, teacher_user_id=%s, words=%d, grammar=%d, exercises=%d)",
        lesson_id, generation_id, owner_user_id, len(draft.words), len(draft.grammar), len(draft.exercises),
    )
    _drafts(context).pop(lesson_id, None)
    if context.user_data.get(_ACTIVE_LESSON_KEY) == lesson_id:
        context.user_data.pop(_ACTIVE_LESSON_KEY, None)
    pending = context.user_data.get(_PENDING_EDITOR_KEY)
    if pending is not None and pending.get("lesson_id") == lesson_id:
        _clear_pending_editor(context)
    if query is not None:
        text, markup = _save_success_screen(lesson_id, saved_summary)
        await query.edit_message_text(text, reply_markup=markup)


async def _handle_editor_pending_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    from app.handlers.teacher import _optional_value, is_teacher

    pending = context.user_data.get(_PENDING_EDITOR_KEY)

    if not is_teacher(update, context) or update.effective_message is None or pending is None:
        _clear_pending_editor(context)
        return False

    lesson_id = pending["lesson_id"]
    pending_revision = pending.get("revision")
    db: Database = context.application.bot_data["db"]
    summary = _authorize(_lesson_service(db), lesson_id)
    state = _get_state(context, lesson_id)
    draft = state.get("draft") if state is not None else None
    if summary is None or state is None or draft is None:
        _clear_pending_editor(context)
        await update.effective_message.reply_text(_EDITOR_STALE_MESSAGE)
        return True
    if state.get("draft_revision") != pending_revision:
        # The draft was regenerated (Draft A -> Draft B) while this text input was
        # pending; it must not be applied to the new draft under the old word index.
        _clear_pending_editor(context)
        await update.effective_message.reply_text(_EDITOR_STALE_MESSAGE)
        return True

    raw_value = update.effective_message.text or ""
    action = pending.get("action")

    if action == "edit_field":
        index = pending["index"]
        field = pending["field"]
        try:
            new_draft = update_word_field(draft, index, field, raw_value)
        except DraftEditIndexError:
            _clear_pending_editor(context)
            await update.effective_message.reply_text(_EDITOR_STALE_MESSAGE)
            return True
        except DraftEditError as exc:
            await update.effective_message.reply_text(str(exc), reply_markup=_editor_input_cancel_markup(lesson_id, pending_revision))
            return True

        state["draft"] = new_draft
        _clear_pending_editor(context)
        result = _word_detail_screen(lesson_id, new_draft, index, pending_revision)
        if result is None:
            await update.effective_message.reply_text(_EDITOR_STALE_MESSAGE)
            return True
        text, markup = result
        await update.effective_message.reply_text("✅ Изменено.\n\n" + text, reply_markup=markup)
        return True

    if action == "add_word":
        step = pending.get("step")

        if step == "source":
            value = raw_value.strip()
            if not value:
                await update.effective_message.reply_text(
                    "Слово не может быть пустым. Введите слово ещё раз:",
                    reply_markup=_editor_input_cancel_markup(lesson_id, pending_revision),
                )
                return True
            pending["source"] = value
            pending["step"] = "translation"
            await update.effective_message.reply_text("Введите перевод:", reply_markup=_editor_input_cancel_markup(lesson_id, pending_revision))
            return True

        if step == "translation":
            value = raw_value.strip()
            if not value:
                await update.effective_message.reply_text(
                    "Перевод не может быть пустым. Введите перевод ещё раз:",
                    reply_markup=_editor_input_cancel_markup(lesson_id, pending_revision),
                )
                return True
            pending["translation"] = value
            pending["step"] = "example"
            await update.effective_message.reply_text(
                "Введите пример (необязательно).\nОтправьте «-», чтобы пропустить.",
                reply_markup=_editor_input_cancel_markup(lesson_id, pending_revision),
            )
            return True

        if step == "example":
            example = _optional_value(raw_value)
            try:
                new_draft = add_word(draft, source=pending["source"], translation=pending["translation"], example=example)
            except DraftEditError as exc:
                await update.effective_message.reply_text(str(exc), reply_markup=_editor_input_cancel_markup(lesson_id, pending_revision))
                return True

            state["draft"] = new_draft
            _clear_pending_editor(context)
            new_index = len(new_draft.words) - 1
            result = _word_detail_screen(lesson_id, new_draft, new_index, pending_revision)
            text, markup = result  # a word we just appended is always a valid index
            await update.effective_message.reply_text("✅ Слово добавлено.\n\n" + text, reply_markup=markup)
            return True

    logger.warning("Unknown AI draft editor pending action: %r", action)
    _clear_pending_editor(context)
    return False


async def handle_teacher_ai_draft_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    action = context.user_data.get("teacher_action")
    if action == _TEACHER_ACTION_EDITOR_INPUT:
        return await _handle_editor_pending_message(update, context)
    if action != _TEACHER_ACTION_TOPIC:
        return False

    from app.handlers.teacher import is_teacher

    lesson_id = context.user_data.get(_ACTIVE_LESSON_KEY)

    if not is_teacher(update, context) or update.effective_message is None:
        if lesson_id is not None:
            _clear_state(context, lesson_id)
        else:
            context.user_data.pop("teacher_action", None)
        return False

    state = _get_state(context, lesson_id) if lesson_id is not None else None
    if state is None:
        context.user_data.pop(_ACTIVE_LESSON_KEY, None)
        context.user_data.pop("teacher_action", None)
        return False

    db: Database = context.application.bot_data["db"]
    summary = _authorize(_lesson_service(db), lesson_id)
    if summary is None:
        _clear_state(context, lesson_id)
        await update.effective_message.reply_text(_DRAFT_LOST_MESSAGE)
        return True

    raw_topic = update.effective_message.text or ""
    try:
        topic = validate_topic(raw_topic)
    except DraftRequestValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return True

    state["topic"] = topic
    context.user_data.pop("teacher_action", None)
    text, markup = _level_step_screen(lesson_id)
    await update.effective_message.reply_text(text, reply_markup=markup)
    return True


async def handle_teacher_ai_draft_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    from app.handlers.teacher import is_teacher

    if not is_teacher(update, context):
        return

    data = query.data or ""
    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)

    if data.startswith(TEACHER_AI_DRAFT_START_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_START_PREFIX)
        summary = _authorize(service, lesson_id)
        if summary is None:
            await query.edit_message_text("Урок недоступен.")
            return
        if _has_existing_content(summary):
            text, markup = _existing_content_warning_screen(lesson_id)
            await query.edit_message_text(text, reply_markup=markup)
            return
        await _begin_wizard(update, context, lesson_id)
        return

    if data.startswith(TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_WARNING_CONTINUE_PREFIX)
        summary = _authorize(service, lesson_id)
        if summary is None:
            await query.edit_message_text("Урок недоступен.")
            return
        await _begin_wizard(update, context, lesson_id)
        return

    if data.startswith(TEACHER_AI_DRAFT_LEVEL_PREFIX):
        parsed = _parse_lesson_and_value(data, TEACHER_AI_DRAFT_LEVEL_PREFIX)
        if parsed is None:
            return
        lesson_id, raw_level = parsed
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id)
        if summary is None or state is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        try:
            level = validate_level(raw_level)
        except DraftRequestValidationError:
            return
        state["level"] = level
        text, markup = _words_step_screen(lesson_id)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_WORDS_PREFIX):
        parsed = _parse_lesson_and_value(data, TEACHER_AI_DRAFT_WORDS_PREFIX)
        if parsed is None:
            return
        lesson_id, raw_value = parsed
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id)
        if summary is None or state is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        if not raw_value.isdigit() or int(raw_value) not in ALLOWED_WORDS_COUNTS:
            return
        state["words_count"] = int(raw_value)
        text, markup = _grammar_step_screen(lesson_id)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_GRAMMAR_PREFIX):
        parsed = _parse_lesson_and_value(data, TEACHER_AI_DRAFT_GRAMMAR_PREFIX)
        if parsed is None:
            return
        lesson_id, raw_value = parsed
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id)
        if summary is None or state is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        if not raw_value.isdigit() or int(raw_value) not in ALLOWED_GRAMMAR_COUNTS:
            return
        state["grammar_count"] = int(raw_value)
        text, markup = _exercises_step_screen(lesson_id)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EXERCISES_PREFIX):
        parsed = _parse_lesson_and_value(data, TEACHER_AI_DRAFT_EXERCISES_PREFIX)
        if parsed is None:
            return
        lesson_id, raw_value = parsed
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id)
        if summary is None or state is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        if not raw_value.isdigit() or int(raw_value) not in ALLOWED_EXERCISES_COUNTS:
            return
        state["exercises_count"] = int(raw_value)

        try:
            build_generation_request(
                lesson_id=lesson_id,
                topic=state["topic"],
                level=state["level"],
                words_count=state["words_count"],
                grammar_count=state["grammar_count"],
                exercises_count=int(raw_value),
            )
        except DraftRequestValidationError as exc:
            await query.edit_message_text(str(exc), reply_markup=InlineKeyboardMarkup([[_cancel_button(lesson_id)]]))
            return

        text, markup = _confirm_screen(lesson_id, summary, state)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDIT_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_EDIT_PREFIX)
        summary = _authorize(service, lesson_id)
        if summary is None:
            await query.edit_message_text("Урок недоступен.")
            return
        await _begin_wizard(update, context, lesson_id)
        return

    if data.startswith(TEACHER_AI_DRAFT_CANCEL_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_CANCEL_PREFIX)
        if lesson_id is None:
            return
        _clear_state(context, lesson_id)
        summary = service.get_lesson_summary(lesson_id)
        if summary is None:
            await query.edit_message_text("Урок не найден.")
            return
        await show_ai_draft_entry(update, context, lesson_id, summary, edit=True)
        return

    if data.startswith(TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_CONFIRM_GENERATE_PREFIX)
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id) if lesson_id is not None else None
        if summary is None or state is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id or 0)]]))
            return
        await _run_generation(update, context, lesson_id, state)
        return

    if data.startswith(TEACHER_AI_DRAFT_REGENERATE_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_REGENERATE_PREFIX)
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id) if lesson_id is not None else None
        if summary is None or state is None or state.get("topic") is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id or 0)]]))
            return
        await _run_generation(update, context, lesson_id, state)
        return

    if data.startswith(TEACHER_AI_DRAFT_READY_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_READY_PREFIX)
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id) if lesson_id is not None else None
        if summary is None or state is None or state.get("draft") is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id or 0)]]))
            return
        text, markup = _ready_screen(lesson_id, state["draft"])
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_PREVIEW_OPEN_PREFIX)
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id) if lesson_id is not None else None
        if summary is None or state is None or state.get("draft") is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id or 0)]]))
            return
        text, markup = _preview_menu_screen(lesson_id, state["draft"])
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_PREVIEW_SECTION_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
            return
        lesson_id = int(parts[0])
        section = parts[1]
        page = int(parts[2])
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id)
        if summary is None or state is None or state.get("draft") is None:
            await query.edit_message_text(_DRAFT_LOST_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        result = _preview_section_screen(lesson_id, state["draft"], section, page)
        if result is None:
            text, markup = _preview_menu_screen(lesson_id, state["draft"])
            await query.edit_message_text(text, reply_markup=markup)
            return
        text, markup = result
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_SAVE_PREFIX):
        lesson_id = _parse_lesson_id(data, TEACHER_AI_DRAFT_SAVE_PREFIX)
        summary = _authorize(service, lesson_id)
        state = _get_state(context, lesson_id) if lesson_id is not None else None
        if summary is None or state is None:
            await query.edit_message_text(
                _DRAFT_NOT_FOUND_FOR_SAVE_MESSAGE,
                reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id or 0)]]),
            )
            return
        await _save_draft_to_lesson(update, context, lesson_id, state, summary)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_OPEN_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        text, markup = _editor_overview_screen(lesson_id, draft, revision)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_WORDS_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1] or not parts[2].isdigit():
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        page = int(parts[2])
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        text, markup = _words_list_screen(lesson_id, draft, page, revision)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_WORD_ADD_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        context.user_data[_PENDING_EDITOR_KEY] = {
            "lesson_id": lesson_id,
            "revision": revision,
            "section": "words",
            "action": "add_word",
            "step": "source",
            "index": None,
            "field": None,
            "source": None,
            "translation": None,
        }
        context.user_data["teacher_action"] = _TEACHER_ACTION_EDITOR_INPUT
        await query.edit_message_text("Введите английское слово:", reply_markup=_editor_input_cancel_markup(lesson_id, revision))
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_WORD_EDIT_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 4 or not parts[0].isdigit() or not parts[1] or not parts[2].isdigit() or parts[3] not in _WORD_FIELD_CODES_REVERSE:
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        index = int(parts[2])
        field = _WORD_FIELD_CODES_REVERSE[parts[3]]
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None or not (0 <= index < len(draft.words)):
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        context.user_data[_PENDING_EDITOR_KEY] = {
            "lesson_id": lesson_id,
            "revision": revision,
            "section": "words",
            "action": "edit_field",
            "index": index,
            "field": field,
        }
        context.user_data["teacher_action"] = _TEACHER_ACTION_EDITOR_INPUT
        await query.edit_message_text(_WORD_FIELD_PROMPTS[field], reply_markup=_editor_input_cancel_markup(lesson_id, revision))
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_CONFIRM_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1] or not parts[2].isdigit():
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        index = int(parts[2])
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        try:
            new_draft = delete_word(draft, index)
        except DraftEditIndexError:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        state = _get_state(context, lesson_id)
        state["draft"] = new_draft
        text, markup = _words_list_screen(lesson_id, new_draft, 0, revision)
        await query.edit_message_text("✅ Слово удалено.\n\n" + text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_WORD_DELETE_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1] or not parts[2].isdigit():
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        index = int(parts[2])
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        result = _word_delete_confirm_screen(lesson_id, draft, index, revision)
        if result is None:
            text, markup = _words_list_screen(lesson_id, draft, 0, revision)
            await query.edit_message_text(text, reply_markup=markup)
            return
        text, markup = result
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_WORD_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1] or not parts[2].isdigit():
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        index = int(parts[2])
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        result = _word_detail_screen(lesson_id, draft, index, revision)
        if result is None:
            text, markup = _words_list_screen(lesson_id, draft, 0, revision)
            await query.edit_message_text(text, reply_markup=markup)
            return
        text, markup = result
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_CANCEL_INPUT_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        pending = context.user_data.get(_PENDING_EDITOR_KEY)
        pending_belongs = pending is not None and pending.get("lesson_id") == lesson_id
        pending_action = pending.get("action") if pending_belongs else None
        pending_index = pending.get("index") if pending_belongs else None
        # On a stale revision, _resolve_editor_action clears `pending` itself (only if
        # it belongs to that same stale revision) and returns None below.
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        if pending_belongs:
            _clear_pending_editor(context)
        if pending_action == "edit_field" and pending_index is not None:
            result = _word_detail_screen(lesson_id, draft, pending_index, revision)
            if result is not None:
                text, markup = result
                await query.edit_message_text(text, reply_markup=markup)
                return
        text, markup = _words_list_screen(lesson_id, draft, 0, revision)
        await query.edit_message_text(text, reply_markup=markup)
        return

    if data.startswith(TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX):
        payload = data.removeprefix(TEACHER_AI_DRAFT_EDITOR_UNAVAILABLE_PREFIX).strip()
        parts = payload.split(":")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1]:
            return
        lesson_id = int(parts[0])
        revision = parts[1]
        draft = _resolve_editor_action(context, service, lesson_id, revision)
        if draft is None:
            await query.edit_message_text(_EDITOR_STALE_MESSAGE, reply_markup=InlineKeyboardMarkup([[_back_to_lesson_button(lesson_id)]]))
            return
        await query.answer(_EDITOR_UNAVAILABLE_MESSAGE, show_alert=True)
        return
