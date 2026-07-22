"""AI Draft Generator v1: in-memory lesson content draft generation.

This module implements the teacher-facing wizard that collects generation
parameters (topic, level, counts), calls the AI generator service, and
lets the teacher preview and regenerate the resulting draft. The draft
never touches SQLite and never changes existing lesson content — it lives
only in `context.user_data` for the duration of the Telegram session.
Saving/merging the draft into a real lesson is explicitly out of scope
for this PR and is left to a future one.
"""

from __future__ import annotations

import logging

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
from app.ai.lesson_draft_generator import generate_lesson_draft
from app.database import Database
from app.lesson_metadata import lesson_display_name
from app.lesson_repository import LESSON_STATUS_DRAFT, LessonRepository
from app.lesson_service import LessonService

logger = logging.getLogger(__name__)

_STATE_KEY = "ai_lesson_drafts"
_ACTIVE_LESSON_KEY = "teacher_ai_draft_active_lesson_id"
_TEACHER_ACTION_TOPIC = "teacher_ai_draft_topic"

_NETWORK_ERROR_MESSAGE = "Не удалось получить ответ от AI-сервиса. Попробуйте ещё раз немного позже."
_INVALID_DRAFT_MESSAGE = "AI вернул некорректный черновик. Можно попробовать сгенерировать его ещё раз."
_DRAFT_LOST_MESSAGE = "Черновик больше недоступен. Сгенерируйте его заново."

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
)

_WORDS_PER_PAGE = 5

_SECTION_LABELS = {
    "words": "📚 Слова",
    "grammar": "📘 Грамматика",
    "exercises": "📝 Упражнения",
}


def _lesson_service(db: Database) -> LessonService:
    return LessonService(LessonRepository(db))


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


def _clear_state(context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    _drafts(context).pop(lesson_id, None)
    if context.user_data.get(_ACTIVE_LESSON_KEY) == lesson_id:
        context.user_data.pop(_ACTIVE_LESSON_KEY, None)
        if context.user_data.get("teacher_action") == _TEACHER_ACTION_TOPIC:
            context.user_data.pop("teacher_action", None)


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
        [InlineKeyboardButton("🔄 Сгенерировать заново", callback_data=f"{TEACHER_AI_DRAFT_REGENERATE_PREFIX}{lesson_id}")],
        [_cancel_button(lesson_id)],
    ])
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


async def _begin_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    _drafts(context)[lesson_id] = {
        "topic": None,
        "level": None,
        "words_count": None,
        "grammar_count": None,
        "exercises_count": None,
        "in_progress": False,
        "draft": None,
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
        state["request"] = request
        if query is not None:
            text, markup = _ready_screen(lesson_id, draft)
            await query.edit_message_text(text, reply_markup=markup)
    finally:
        state["in_progress"] = False


async def handle_teacher_ai_draft_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if context.user_data.get("teacher_action") != _TEACHER_ACTION_TOPIC:
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
