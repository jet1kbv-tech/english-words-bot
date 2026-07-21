from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver
from app.database import Database
from app.handlers.start import require_user
from app.handlers.training import start_lesson_words_practice
from app.keyboards import MY_LESSONS, main_menu_keyboard
from app.lesson_metadata import lesson_display_name
from app.lesson_repository import LessonRepository
from app.lesson_runtime import LessonRuntimeService, LessonSection

STUDENT_LESSONS_LIST_CALLBACK = "student:lessons:list"
STUDENT_LESSON_OPEN_PREFIX = "student:lesson:open:"
STUDENT_LESSON_START_PREFIX = "student:lesson:start:"
STUDENT_LESSON_WORDS_CARDS_PREFIX = "student:lesson:words:cards:"
STUDENT_LESSON_WORDS_TYPE_PREFIX = "student:lesson:words:type:"
STUDENT_LESSON_WORDS_PREFIX = "student:lesson:words:"
STUDENT_LESSON_CALLBACK_PREFIXES = (
    STUDENT_LESSONS_LIST_CALLBACK,
    STUDENT_LESSON_OPEN_PREFIX,
    STUDENT_LESSON_START_PREFIX,
    STUDENT_LESSON_WORDS_CARDS_PREFIX,
    STUDENT_LESSON_WORDS_TYPE_PREFIX,
    STUDENT_LESSON_WORDS_PREFIX,
)


def _repository(context: ContextTypes.DEFAULT_TYPE) -> LessonRepository:
    db: Database = context.application.bot_data["db"]
    return LessonRepository(db)


def _count(summary, key: str) -> int:
    return int(summary[key] or 0) if hasattr(summary, "keys") and key in summary.keys() else 0


def _format_student_lessons(lessons: list) -> str:
    if not lessons:
        return "📚 Мои уроки\n\nУ вас пока нет назначенных уроков.\n\nКогда преподаватель назначит первый урок, он появится здесь."
    lines = ["📚 Мои уроки", "", "Ваши уроки:", ""]
    lines.extend(f"▶ {lesson_display_name(lesson)}" for lesson in lessons)
    return "\n".join(lines)


def _student_lessons_keyboard(lessons: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"▶ {lesson_display_name(lesson)}", callback_data=f"{STUDENT_LESSON_OPEN_PREFIX}{lesson['id']}")] for lesson in lessons]
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data=STUDENT_LESSONS_LIST_CALLBACK + ":menu")])
    return InlineKeyboardMarkup(rows)


def _format_student_lesson_overview(summary) -> str:
    return "\n".join([
        "📚 Урок",
        "",
        lesson_display_name(summary),
        "",
        "Статус:",
        "",
        "Не начат",
        "",
        "Прогресс урока",
        "",
        "🟢 Слова",
        "⚪ Грамматика",
        "⚪ Упражнения",
        "⚪ Домашнее задание",
        "",
        f"Слова: {_count(summary, 'words_count')}",
        f"Грамматика: {_count(summary, 'grammar_count')}",
        f"Упражнения: {_count(summary, 'exercises_count')}",
        f"Домашнее задание: {_count(summary, 'homework_count')}",
    ])


def _student_lesson_overview_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶ Начать урок", callback_data=f"{STUDENT_LESSON_START_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("⬅️ Мои уроки", callback_data=STUDENT_LESSONS_LIST_CALLBACK)],
    ])


def _lesson_unavailable_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Мои уроки", callback_data=STUDENT_LESSONS_LIST_CALLBACK)]])


def _start_section_keyboard(lesson_id: int, section: LessonSection) -> InlineKeyboardMarkup:
    open_callback = f"{STUDENT_LESSON_WORDS_PREFIX}{lesson_id}" if section is LessonSection.WORDS else f"{STUDENT_LESSON_OPEN_PREFIX}{lesson_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶ Открыть", callback_data=open_callback)],
        [InlineKeyboardButton("⬅️ Урок", callback_data=f"{STUDENT_LESSON_OPEN_PREFIX}{lesson_id}")],
    ])


def _lesson_back_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Урок", callback_data=f"{STUDENT_LESSON_OPEN_PREFIX}{lesson_id}")]])


def _format_next_section(summary, section: LessonSection) -> str:
    if section is LessonSection.WORDS:
        return "\n".join(["Следующий этап", "", "📖 Слова", "", f"{_count(summary, 'words_count')} слова"])
    return "Следующий этап будет добавлен позже."


def _format_words_stage(summary) -> str:
    words_count = _count(summary, "words_count")
    if words_count == 0:
        return "\n".join(["📖 Слова", "", "В этом уроке пока нет слов.", "", "Попросите преподавателя добавить слова."])
    return "\n".join([
        "📖 Слова",
        "",
        f"Слов в уроке: {words_count}",
        "",
        "Выберите режим прохождения:",
        "",
        "🃏 Карточки — вспоминаешь и отмечаешь Помню / Не помню.",
        "✍️ Ввод — пишешь ответ в чат, бот проверяет.",
    ])


def _words_stage_keyboard(lesson_id: int, has_words: bool) -> InlineKeyboardMarkup:
    if not has_words:
        return _lesson_back_keyboard(lesson_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Карточки", callback_data=f"{STUDENT_LESSON_WORDS_CARDS_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("✍️ Ввод", callback_data=f"{STUDENT_LESSON_WORDS_TYPE_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("⬅️ Урок", callback_data=f"{STUDENT_LESSON_OPEN_PREFIX}{lesson_id}")],
    ])


def _is_student_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    resolver = RoleResolver(context.application.bot_data["settings"], context.application.bot_data.get("db"))
    role = resolver.role_for(user.username)
    if role is Role.TEACHER:
        return bool(context.user_data.get("impersonated_user_id"))
    if role is Role.ADMIN:
        return not bool(context.user_data.get("admin_teacher_view"))
    return role is Role.STUDENT


async def show_student_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    lessons = _repository(context).list_student_lessons(user["username"])
    await update.effective_message.reply_text(_format_student_lessons(lessons), reply_markup=_student_lessons_keyboard(lessons))


async def handle_student_lesson_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_message is None or not _is_student_flow(update, context):
        return False
    if update.effective_message.text == MY_LESSONS:
        await show_student_lessons(update, context)
        return True
    return False


async def handle_student_lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not _is_student_flow(update, context):
        return
    await query.answer()
    user = await require_user(update, context)
    if user is None:
        return
    data = query.data or ""
    repo = _repository(context)
    if data == STUDENT_LESSONS_LIST_CALLBACK:
        lessons = repo.list_student_lessons(user["username"])
        await query.edit_message_text(_format_student_lessons(lessons), reply_markup=_student_lessons_keyboard(lessons))
        return
    if data == STUDENT_LESSONS_LIST_CALLBACK + ":menu":
        if query.message is not None:
            await query.message.reply_text("Меню", reply_markup=main_menu_keyboard(include_exit_student_mode=bool(context.user_data.get("impersonated_user_id")), include_admin=RoleResolver(context.application.bot_data["settings"], context.application.bot_data.get("db")).role_for(update.effective_user.username) is Role.ADMIN))
        return
    if data.startswith(STUDENT_LESSON_OPEN_PREFIX):
        lesson_id_text = data.removeprefix(STUDENT_LESSON_OPEN_PREFIX)
        if not lesson_id_text.isdigit():
            await query.edit_message_text("Урок недоступен.", reply_markup=_lesson_unavailable_keyboard())
            return
        lesson_id = int(lesson_id_text)
        summary = repo.get_student_lesson(lesson_id, user["username"])
        if summary is None:
            await query.edit_message_text("Урок недоступен.", reply_markup=_lesson_unavailable_keyboard())
            return
        await query.edit_message_text(_format_student_lesson_overview(summary), reply_markup=_student_lesson_overview_keyboard(lesson_id))
        return
    if data.startswith(STUDENT_LESSON_START_PREFIX):
        lesson_id_text = data.removeprefix(STUDENT_LESSON_START_PREFIX)
        lesson_id = int(lesson_id_text) if lesson_id_text.isdigit() else 0
        summary = repo.get_student_lesson(lesson_id, user["username"]) if lesson_id > 0 else None
        if summary is None:
            await query.edit_message_text("Урок недоступен.", reply_markup=_lesson_unavailable_keyboard())
            return
        section = LessonRuntimeService(repo).get_next_section(lesson_id, user["username"])
        if section is None:
            await query.edit_message_text("Урок недоступен.", reply_markup=_lesson_unavailable_keyboard())
            return
        await query.edit_message_text(_format_next_section(summary, section), reply_markup=_start_section_keyboard(lesson_id, section))
        return
    for mode_prefix, typed in ((STUDENT_LESSON_WORDS_CARDS_PREFIX, False), (STUDENT_LESSON_WORDS_TYPE_PREFIX, True)):
        if not data.startswith(mode_prefix):
            continue
        lesson_id_text = data.removeprefix(mode_prefix)
        lesson_id = int(lesson_id_text) if lesson_id_text.isdigit() else 0
        summary = repo.get_student_lesson(lesson_id, user["username"]) if lesson_id > 0 else None
        if summary is None:
            await query.edit_message_text("Урок недоступен.", reply_markup=_lesson_unavailable_keyboard())
            return
        words = repo.list_lesson_training_words(lesson_id, int(user["id"]))
        if not words:
            await query.edit_message_text(_format_words_stage(summary), reply_markup=_words_stage_keyboard(lesson_id, has_words=False))
            return
        await start_lesson_words_practice(update, context, words, typed=typed)
        return
    if data.startswith(STUDENT_LESSON_WORDS_PREFIX):
        lesson_id_text = data.removeprefix(STUDENT_LESSON_WORDS_PREFIX)
        lesson_id = int(lesson_id_text) if lesson_id_text.isdigit() else 0
        summary = repo.get_student_lesson(lesson_id, user["username"]) if lesson_id > 0 else None
        if summary is None:
            await query.edit_message_text("Урок недоступен.", reply_markup=_lesson_unavailable_keyboard())
            return
        has_words = _count(summary, "words_count") > 0
        await query.edit_message_text(_format_words_stage(summary), reply_markup=_words_stage_keyboard(lesson_id, has_words=has_words))
