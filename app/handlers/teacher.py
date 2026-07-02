from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver
from app.config import Settings
from app.database import Database
from app.handlers.training import _today_moscow
from app.keyboards import ADD_STUDENT, EXIT_STUDENT_MODE, TEACHER_CREATE_LESSON, TEACHER_IMPERSONATE, TEACHER_LESSONS, TEACHER_MY_LESSONS, TEACHER_PROGRESS, TEACHER_STUDENTS, main_menu_keyboard, teacher_lessons_keyboard, teacher_menu_keyboard
from app.lesson_metadata import lesson_display_name
from app.lesson_repository import LessonRepository
from app.lesson_service import LessonService, LessonWordImportError, normalize_lesson_words_import
from app.student_access_service import StudentAccessService

_SELECT_PROGRESS = "teacher_select_progress"
_SELECT_IMPERSONATE = "teacher_select_impersonate"
_CREATE_LESSON_STUDENT = "teacher_create_lesson_student"
_CREATE_LESSON_TITLE = "teacher_create_lesson_title"
_CREATE_LESSON_THEME = "teacher_create_lesson_theme"
_CREATE_LESSON_GRAMMAR = "teacher_create_lesson_grammar"
_OPTIONAL_SKIP = {"", "-", "пропустить", "skip"}
_ADD_STUDENT = "teacher_add_student"
_IMPORT_LESSON_WORDS = "teacher_import_lesson_words"
_PENDING_LESSON_WORDS = "pending_lesson_words"
NOT_STARTED_TEXT = "Ученик ещё не запускал бота. Попросите его открыть бота и нажать /start."

LESSON_BACK_TO_LIST = "⬅️ К списку lessons"
TEACHER_LESSONS_BACK = "⬅️ Назад"
TEACHER_LESSON_OPEN_PREFIX = "Lesson "
TEACHER_LESSON_WORDS_PREFIX = "teacher:lesson:words:"
TEACHER_LESSON_GRAMMAR_PREFIX = "teacher:lesson:grammar:"
TEACHER_LESSON_EXERCISES_PREFIX = "teacher:lesson:exercises:"
TEACHER_LESSON_HOMEWORK_PREFIX = "teacher:lesson:homework:"
TEACHER_LESSON_AI_PREFIX = "teacher:lesson:ai:"
TEACHER_LESSON_BACK_PREFIX = "teacher:lesson:back:"
TEACHER_LESSON_WORDS_ADD_PREFIX = "teacher:lesson:words:add:"
TEACHER_LESSON_WORDS_CONFIRM_PREFIX = "teacher:lesson:words:confirm:"
TEACHER_LESSON_WORDS_CANCEL_PREFIX = "teacher:lesson:words:cancel:"
TEACHER_LESSONS_LIST_CALLBACK = "teacher:lessons:list"
TEACHER_LESSON_CALLBACK_PREFIXES = (
    TEACHER_LESSON_WORDS_PREFIX,
    TEACHER_LESSON_GRAMMAR_PREFIX,
    TEACHER_LESSON_EXERCISES_PREFIX,
    TEACHER_LESSON_HOMEWORK_PREFIX,
    TEACHER_LESSON_AI_PREFIX,
    TEACHER_LESSON_BACK_PREFIX,
    TEACHER_LESSON_WORDS_ADD_PREFIX,
    TEACHER_LESSON_WORDS_CONFIRM_PREFIX,
    TEACHER_LESSON_WORDS_CANCEL_PREFIX,
)


def _lesson_service(db: Database) -> LessonService:
    return LessonService(LessonRepository(db))


def _status_label(status: str) -> str:
    return status[:1].upper() + status[1:].lower()


def _format_lessons_screen(lessons: list) -> str:
    if not lessons:
        return "📚 Lessons\n\nПока нет уроков.\n\nСоздайте первый урок."
    lines = ["📚 Lessons", ""]
    for index, lesson in enumerate(lessons, start=1):
        lines.append(f"{index}. {lesson_display_name(lesson)} — {_status_label(lesson['status'])}")
    return "\n".join(lines)


def _lessons_list_keyboard(lessons: list) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(f"Lesson {lesson['id']}")] for lesson in lessons]
    rows.append([KeyboardButton(TEACHER_CREATE_LESSON)])
    rows.append([KeyboardButton(TEACHER_LESSONS_BACK)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _count(summary, key: str) -> int:
    return int(summary[key] or 0) if key in summary.keys() else 0


def _optional_summary_value(summary, key: str) -> str:
    if hasattr(summary, "keys") and key in summary.keys() and summary[key]:
        return str(summary[key])
    return "—"


def _format_lesson_detail(summary) -> str:
    return "\n".join([
        "📚 Lesson",
        "",
        f"Lesson: {lesson_display_name(summary)}",
        f"Status: {_status_label(summary['status'])}",
        "",
        f"Topic: {_optional_summary_value(summary, 'topic')}",
        f"Level: {_optional_summary_value(summary, 'level')}",
        f"Description: {_optional_summary_value(summary, 'description')}",
        "",
        f"📖 Words: {_count(summary, 'words_count')}",
        f"📝 Grammar: {_count(summary, 'grammar_count')}",
        f"✏️ Exercises: {_count(summary, 'exercises_count')}",
        f"🏠 Homework: {_count(summary, 'homework_count')}",
    ])


def _lesson_detail_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Words", callback_data=f"{TEACHER_LESSON_WORDS_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("📝 Grammar", callback_data=f"{TEACHER_LESSON_GRAMMAR_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("✏️ Exercises", callback_data=f"{TEACHER_LESSON_EXERCISES_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("🏠 Homework", callback_data=f"{TEACHER_LESSON_HOMEWORK_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("🤖 AI Assistant", callback_data=f"{TEACHER_LESSON_AI_PREFIX}{lesson_id}")],
        [InlineKeyboardButton(LESSON_BACK_TO_LIST, callback_data=TEACHER_LESSONS_LIST_CALLBACK)],
    ])



def _format_lesson_words(words: list) -> str:
    if not words:
        return "📖 Words\n\nВ этом уроке пока нет слов."
    lines = ["📖 Words", "", f"Всего слов: {len(words)}", ""]
    lines.extend(f"• {word['text']}" for word in words)
    return "\n".join(lines)


def _lesson_words_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить слова", callback_data=f"{TEACHER_LESSON_WORDS_ADD_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("⬅️ Lesson", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")],
    ])


def _format_lesson_words_preview(words: list[str]) -> str:
    return "\n".join(["Будут добавлены:", "", *(f"{index}. {word}" for index, word in enumerate(words, start=1))])


def _lesson_words_preview_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сохранить", callback_data=f"{TEACHER_LESSON_WORDS_CONFIRM_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"{TEACHER_LESSON_WORDS_CANCEL_PREFIX}{lesson_id}")],
    ])


def _lesson_words_prompt() -> str:
    return "Отправьте список слов.\n\nКаждое слово с новой строки.\n\nНапример\n\nreceipt\nworth it\nstale"


async def _show_lesson_words(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, *, edit: bool = False) -> None:
    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)
    words = service.list_lesson_words(lesson_id)
    text = _format_lesson_words(words)
    markup = _lesson_words_keyboard(lesson_id)
    if edit and update.callback_query is not None:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=markup)


def _format_lesson_section(summary, section: str) -> str:
    descriptions = {
        "words": ("📖 Words", "Этот раздел скоро позволит добавлять и редактировать слова урока."),
        "grammar": ("📝 Grammar", "Этот раздел скоро позволит добавлять грамматическую тему и объяснения."),
        "exercises": ("✏️ Exercises", "Этот раздел скоро позволит добавлять упражнения урока."),
        "homework": ("🏠 Homework", "Этот раздел скоро позволит собрать домашнее задание по уроку."),
        "ai": ("🤖 AI Assistant", "Скоро здесь можно будет сгенерировать слова, упражнения, домашку и подсказки с помощью AI."),
    }
    title, description = descriptions[section]
    return "\n".join([title, "", description, "", f"Lesson: {lesson_display_name(summary)}"])


def _lesson_section_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К lesson", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")]])


async def _show_lessons_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    lessons = _lesson_service(db).list_lessons()
    context.user_data.pop("teacher_action", None)
    if update.effective_message:
        await update.effective_message.reply_text(_format_lessons_screen(lessons), reply_markup=_lessons_list_keyboard(lessons))


async def _show_lesson_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    summary = _lesson_service(db).get_lesson_summary(lesson_id)
    if update.effective_message is None:
        return
    if summary is None:
        await update.effective_message.reply_text("Lesson не найден.", reply_markup=_lessons_list_keyboard(_lesson_service(db).list_lessons()))
        return
    context.user_data["current_teacher_lesson_id"] = lesson_id
    await update.effective_message.reply_text(_format_lesson_detail(summary), reply_markup=_lesson_detail_keyboard(lesson_id))



def _lesson_id_from_callback(data: str, prefix: str) -> int | None:
    lesson_id_text = data.removeprefix(prefix).strip()
    return int(lesson_id_text) if lesson_id_text.isdigit() else None


async def handle_teacher_lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if not is_teacher(update, context):
        return
    data = query.data or ""
    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)
    if data == TEACHER_LESSONS_LIST_CALLBACK:
        lessons = service.list_lessons()
        if query.message is not None:
            await query.message.reply_text(_format_lessons_screen(lessons), reply_markup=_lessons_list_keyboard(lessons))
        return
    for words_prefix in (TEACHER_LESSON_WORDS_ADD_PREFIX, TEACHER_LESSON_WORDS_CONFIRM_PREFIX, TEACHER_LESSON_WORDS_CANCEL_PREFIX):
        if not data.startswith(words_prefix):
            continue
        lesson_id = _lesson_id_from_callback(data, words_prefix)
        if lesson_id is None or service.get_lesson_summary(lesson_id) is None:
            if query.message is not None:
                await query.message.reply_text("Lesson не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        context.user_data["current_teacher_lesson_id"] = lesson_id
        if words_prefix == TEACHER_LESSON_WORDS_ADD_PREFIX:
            context.user_data["teacher_action"] = _IMPORT_LESSON_WORDS
            context.user_data[_PENDING_LESSON_WORDS] = {"lesson_id": lesson_id, "source": "manual", "words": []}
            if query.message is not None:
                await query.message.reply_text(_lesson_words_prompt())
            return
        draft = context.user_data.get(_PENDING_LESSON_WORDS)
        if words_prefix == TEACHER_LESSON_WORDS_CANCEL_PREFIX:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_LESSON_WORDS, None)
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        if not draft or int(draft.get("lesson_id", 0)) != lesson_id or not draft.get("words"):
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        service.add_lesson_words(lesson_id, list(draft["words"]), owner_user_id=_teacher_user_id(update, db))
        context.user_data.pop("teacher_action", None)
        context.user_data.pop(_PENDING_LESSON_WORDS, None)
        await _show_lesson_words(update, context, lesson_id, edit=True)
        return
    for prefix in TEACHER_LESSON_CALLBACK_PREFIXES:
        if not data.startswith(prefix):
            continue
        lesson_id = _lesson_id_from_callback(data, prefix)
        if lesson_id is None:
            return
        summary = service.get_lesson_summary(lesson_id)
        if summary is None:
            if query.message is not None:
                await query.message.reply_text("Lesson не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        context.user_data["current_teacher_lesson_id"] = lesson_id
        if prefix == TEACHER_LESSON_BACK_PREFIX:
            await query.edit_message_text(_format_lesson_detail(summary), reply_markup=_lesson_detail_keyboard(lesson_id))
            return
        section_by_prefix = {
            TEACHER_LESSON_WORDS_PREFIX: "words",
            TEACHER_LESSON_GRAMMAR_PREFIX: "grammar",
            TEACHER_LESSON_EXERCISES_PREFIX: "exercises",
            TEACHER_LESSON_HOMEWORK_PREFIX: "homework",
            TEACHER_LESSON_AI_PREFIX: "ai",
        }
        if prefix == TEACHER_LESSON_WORDS_PREFIX:
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        await query.edit_message_text(_format_lesson_section(summary, section_by_prefix[prefix]), reply_markup=_lesson_section_keyboard(lesson_id))
        return

def _resolver(context: ContextTypes.DEFAULT_TYPE) -> RoleResolver:
    settings: Settings = context.application.bot_data["settings"]
    return RoleResolver(settings, context.application.bot_data.get("db"))


def is_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    role = _resolver(context).role_for(user.username)
    return role is Role.TEACHER or (role is Role.ADMIN and bool(context.user_data.get("admin_teacher_view")))


def _student_users(context: ContextTypes.DEFAULT_TYPE) -> list:
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    resolver = _resolver(context)
    student_usernames = set(resolver.student_usernames) | {"wp_bvv"}
    return db.list_student_targets(student_usernames, getattr(settings, "display_names", {}))


def _student_keyboard(students: list, back_label: str = "↩️ Teacher menu") -> ReplyKeyboardMarkup:
    rows = []
    for student in students:
        suffix = " — ещё не запускал бота" if not student.get("has_user", True) else ""
        rows.append([KeyboardButton(f"{student['display_name']} (@{student['username']}){suffix}")])
    rows.append([KeyboardButton(back_label)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _student_by_label(students: list, text: str):
    normalized_text = text.casefold()
    for student in students:
        labels = {
            f"{student['display_name']} (@{student['username']})".casefold(),
            f"{student['display_name']} (@{student['username']}) — ещё не запускал бота".casefold(),
            f"@{student['username']}".casefold(),
            str(student["display_name"]).casefold(),
            str(student["username"]).casefold(),
        }
        if normalized_text in labels:
            return student
    return None


def _optional_value(text: str) -> str | None:
    value = text.strip()
    return None if value.casefold() in _OPTIONAL_SKIP else value


def _teacher_user_id(update: Update, db: Database) -> int | None:
    tg_user = update.effective_user
    if tg_user is None:
        return None
    user = db.get_user_by_telegram_id(tg_user.id)
    return int(user["id"]) if user is not None else None


def _format_created_lesson(lesson, student) -> str:
    return "\n".join(
        [
            "Урок создан",
            f"title: {lesson['title']}",
            f"student: {student['display_name']} (@{student['username']})",
            f"theme: {lesson['theme'] or '-'}",
            f"grammar_topic: {lesson['grammar_topic'] or '-'}",
            f"status={lesson['status']}",
        ]
    )


def _format_teacher_lessons(lessons: list) -> str:
    if not lessons:
        return "Пока нет уроков."
    lines = ["📋 Мои уроки:"]
    for lesson in lessons:
        student = f"{lesson['student_display_name']} (@{lesson['student_username']})"
        lines.append(f"• {lesson['title']} — {student} — theme: {lesson['theme'] or '-'} — status: {lesson['status']}")
    return "\n".join(lines)

def _format_students(students: list) -> str:
    if not students:
        return "Пока нет учеников: student users из allowed users ещё не заходили в бот."
    lines = ["👤 Ученики:"]
    for student in students:
        suffix = " — ещё не запускал бота" if not student.get("has_user", True) else ""
        lines.append(f"• {student['display_name']} (@{student['username']}){suffix}")
    return "\n".join(lines)


def _format_student_progress(db: Database, student) -> str:
    if not student.get("has_user", True) or student.get("id") is None:
        return NOT_STARTED_TEXT
    activity = db.get_daily_activity(student["id"], _today_moscow())
    weak_words = db.list_weak_words(student["id"], limit=10)
    weak_lines = [f"{i}. {word['english']} — {word['translation']} (score: {word['progress_score'] or 0}, forgot: {word['times_forgotten'] or 0})" for i, word in enumerate(weak_words, start=1)]
    if not weak_lines:
        weak_lines = ["пока нет слабых слов"]
    parts = [
        f"📊 Прогресс: {student['display_name']} (@{student['username']})",
        f"• всего слов: {db.count_words(student['id'])}",
        f"• карточек сегодня: {activity['cards_reviewed'] if activity else 0}",
        f"• XP сегодня: {activity['xp_earned'] if activity else 0}",
        f"• streak: {activity['streak_days'] if activity else 0}",
        "",
        "Top-10 слабых слов:",
        *weak_lines,
    ]
    return "\n".join(parts)


async def show_teacher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("teacher_action", None)
    if update.effective_message:
        await update.effective_message.reply_text("Teacher menu:", reply_markup=teacher_menu_keyboard())


async def handle_teacher_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_message is None or not is_teacher(update, context):
        return False
    text = update.effective_message.text or ""
    db: Database = context.application.bot_data["db"]

    if text == EXIT_STUDENT_MODE:
        context.user_data.pop("impersonated_user_id", None)
        context.user_data.pop("teacher_action", None)
        await update.effective_message.reply_text("Вы вышли из режима ученика.", reply_markup=teacher_menu_keyboard())
        return True

    if context.user_data.get("impersonated_user_id"):
        return False

    if text in {"↩️ Teacher menu", TEACHER_LESSONS_BACK, "/start"}:
        await show_teacher_menu(update, context)
        return True
    if text == TEACHER_STUDENTS:
        await update.effective_message.reply_text(_format_students(_student_users(context)), reply_markup=teacher_menu_keyboard())
        return True
    if text == ADD_STUDENT:
        context.user_data["teacher_action"] = _ADD_STUDENT
        await update.effective_message.reply_text("Введите username ученика, например @privetnormalno")
        return True
    if text in {TEACHER_LESSONS, LESSON_BACK_TO_LIST}:
        await _show_lessons_screen(update, context)
        return True
    if text == TEACHER_CREATE_LESSON:
        context.user_data["teacher_action"] = _CREATE_LESSON_TITLE
        context.user_data.pop("lesson_draft", None)
        await update.effective_message.reply_text("Введите название урока.\n\nНапример:\nLesson 15 — Food")
        return True
    if text == TEACHER_MY_LESSONS:
        teacher_id = _teacher_user_id(update, db)
        lessons = db.list_lessons_for_teacher(teacher_id, limit=10) if teacher_id is not None else []
        await update.effective_message.reply_text(_format_teacher_lessons(lessons), reply_markup=teacher_lessons_keyboard())
        return True
    if text.startswith(TEACHER_LESSON_OPEN_PREFIX):
        lesson_id_text = text.removeprefix(TEACHER_LESSON_OPEN_PREFIX).strip()
        if lesson_id_text.isdigit():
            await _show_lesson_detail(update, context, int(lesson_id_text))
            return True

    if text in {TEACHER_PROGRESS, TEACHER_IMPERSONATE}:
        students = _student_users(context)
        if not students:
            await update.effective_message.reply_text("Пока нет учеников для выбора.", reply_markup=teacher_menu_keyboard())
            return True
        context.user_data["teacher_action"] = _SELECT_PROGRESS if text == TEACHER_PROGRESS else _SELECT_IMPERSONATE
        await update.effective_message.reply_text("Выберите ученика:", reply_markup=_student_keyboard(students))
        return True

    action = context.user_data.get("teacher_action")
    if action == _IMPORT_LESSON_WORDS:
        draft = context.user_data.get(_PENDING_LESSON_WORDS) or {}
        lesson_id = int(draft.get("lesson_id") or context.user_data.get("current_teacher_lesson_id") or 0)
        if not lesson_id:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_LESSON_WORDS, None)
            return False
        try:
            words = normalize_lesson_words_import(text)
        except LessonWordImportError as error:
            await update.effective_message.reply_text(str(error))
            return True
        context.user_data[_PENDING_LESSON_WORDS] = {"lesson_id": lesson_id, "source": "manual", "words": words}
        await update.effective_message.reply_text(_format_lesson_words_preview(words), reply_markup=_lesson_words_preview_keyboard(lesson_id))
        return True
    if action == _ADD_STUDENT:
        service = StudentAccessService(db)
        username = service.normalize_username(text)
        if not service.validate_username(username):
            await update.effective_message.reply_text("Не похоже на Telegram username.\n\nВведите username в формате @username.")
            return True
        result = service.add_student_access(username, added_by_user_id=_teacher_user_id(update, db))
        context.user_data.pop("teacher_action", None)
        if result.status == "already_active":
            reply = f"Ученик @{result.username} уже добавлен."
        elif result.status == "reactivated":
            reply = f"Доступ для @{result.username} снова включён ✅"
        else:
            reply = (
                f"Ученик @{result.username} добавлен ✅\n\n"
                "Если он ещё не запускал бота, попросите его открыть бота и нажать /start."
            )
        await update.effective_message.reply_text(reply, reply_markup=teacher_menu_keyboard())
        return True
    if action == _CREATE_LESSON_STUDENT:
        student = _student_by_label(_student_users(context), text)
        if student is None:
            await update.effective_message.reply_text("Не нашёл такого ученика. Выберите ученика из списка.")
            return True
        if not student.get("has_user", True) or student.get("id") is None:
            await update.effective_message.reply_text(NOT_STARTED_TEXT)
            return True
        context.user_data["lesson_draft"] = {"student_user_id": student["id"]}
        context.user_data["teacher_action"] = _CREATE_LESSON_TITLE
        await update.effective_message.reply_text("Введите title урока:")
        return True
    if action == _CREATE_LESSON_TITLE:
        title = text.strip()
        if not title:
            await update.effective_message.reply_text("Название урока не может быть пустым. Введите название урока:")
            return True
        lesson = _lesson_service(db).create_lesson(title, created_by_user_id=_teacher_user_id(update, db))
        context.user_data.pop("teacher_action", None)
        context.user_data.pop("lesson_draft", None)
        await _show_lesson_detail(update, context, int(lesson["id"]))
        return True
    if action == _CREATE_LESSON_THEME:
        context.user_data.setdefault("lesson_draft", {})["theme"] = _optional_value(text)
        context.user_data["teacher_action"] = _CREATE_LESSON_GRAMMAR
        await update.effective_message.reply_text("Введите grammar_topic или '-' чтобы пропустить:")
        return True
    if action == _CREATE_LESSON_GRAMMAR:
        draft = context.user_data.get("lesson_draft", {})
        student = db.get_user_by_id(int(draft["student_user_id"]))
        if student is None:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop("lesson_draft", None)
            await update.effective_message.reply_text("Не нашёл выбранного ученика.", reply_markup=teacher_lessons_keyboard())
            return True
        teacher_id = _teacher_user_id(update, db)
        lesson = db.create_lesson(int(draft["student_user_id"]), teacher_id, draft["title"], draft.get("theme"), _optional_value(text))
        context.user_data.pop("teacher_action", None)
        context.user_data.pop("lesson_draft", None)
        await update.effective_message.reply_text(_format_created_lesson(lesson, student), reply_markup=teacher_lessons_keyboard())
        return True
    if action in {_SELECT_PROGRESS, _SELECT_IMPERSONATE}:
        student = _student_by_label(_student_users(context), text)
        if student is None:
            await update.effective_message.reply_text("Не нашёл такого ученика. Выберите ученика из списка.")
            return True
        context.user_data.pop("teacher_action", None)
        if action == _SELECT_PROGRESS:
            await update.effective_message.reply_text(_format_student_progress(db, student), reply_markup=teacher_menu_keyboard())
            return True
        if not student.get("has_user", True) or student.get("id") is None:
            await update.effective_message.reply_text(NOT_STARTED_TEXT, reply_markup=teacher_menu_keyboard())
            return True
        context.user_data["impersonated_user_id"] = student["id"]
        context.user_data.pop("training", None)
        await update.effective_message.reply_text(
            f"👀 Режим ученика: {student['display_name']}. Действия выполняются как выбранный ученик.",
            reply_markup=main_menu_keyboard(include_exit_student_mode=True),
        )
        return True

    return False
