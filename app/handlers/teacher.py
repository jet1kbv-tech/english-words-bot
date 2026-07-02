from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver
from app.config import Settings
from app.database import Database
from app.handlers.training import _today_moscow
from app.keyboards import EXIT_STUDENT_MODE, TEACHER_CREATE_LESSON, TEACHER_IMPERSONATE, TEACHER_LESSONS, TEACHER_MY_LESSONS, TEACHER_PROGRESS, TEACHER_STUDENTS, main_menu_keyboard, teacher_lessons_keyboard, teacher_menu_keyboard

_SELECT_PROGRESS = "teacher_select_progress"
_SELECT_IMPERSONATE = "teacher_select_impersonate"
_CREATE_LESSON_STUDENT = "teacher_create_lesson_student"
_CREATE_LESSON_TITLE = "teacher_create_lesson_title"
_CREATE_LESSON_THEME = "teacher_create_lesson_theme"
_CREATE_LESSON_GRAMMAR = "teacher_create_lesson_grammar"
_OPTIONAL_SKIP = {"", "-", "пропустить", "skip"}


def _resolver(context: ContextTypes.DEFAULT_TYPE) -> RoleResolver:
    settings: Settings = context.application.bot_data["settings"]
    return RoleResolver(settings)


def is_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    role = _resolver(context).role_for(user.username)
    return role is Role.TEACHER or (role is Role.ADMIN and bool(context.user_data.get("admin_teacher_view")))


def _student_users(context: ContextTypes.DEFAULT_TYPE) -> list:
    db: Database = context.application.bot_data["db"]
    return db.list_student_users(_resolver(context).student_usernames)


def _student_keyboard(students: list, back_label: str = "↩️ Teacher menu") -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(f"{student['display_name']} (@{student['username']})")] for student in students]
    rows.append([KeyboardButton(back_label)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _student_by_label(students: list, text: str):
    normalized_text = text.casefold()
    for student in students:
        labels = {
            f"{student['display_name']} (@{student['username']})".casefold(),
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
    lines.extend(f"• {student['display_name']} (@{student['username']})" for student in students)
    return "\n".join(lines)


def _format_student_progress(db: Database, student) -> str:
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

    if text in {"↩️ Teacher menu", "/start"}:
        await show_teacher_menu(update, context)
        return True
    if text == TEACHER_STUDENTS:
        await update.effective_message.reply_text(_format_students(_student_users(context)), reply_markup=teacher_menu_keyboard())
        return True
    if text == TEACHER_LESSONS:
        context.user_data.pop("teacher_action", None)
        await update.effective_message.reply_text("📚 Уроки:", reply_markup=teacher_lessons_keyboard())
        return True
    if text == TEACHER_CREATE_LESSON:
        students = _student_users(context)
        if not students:
            await update.effective_message.reply_text("Пока нет учеников для выбора.", reply_markup=teacher_lessons_keyboard())
            return True
        context.user_data["teacher_action"] = _CREATE_LESSON_STUDENT
        context.user_data.pop("lesson_draft", None)
        await update.effective_message.reply_text("Выберите ученика:", reply_markup=_student_keyboard(students, back_label="📚 Уроки"))
        return True
    if text == TEACHER_MY_LESSONS:
        teacher_id = _teacher_user_id(update, db)
        lessons = db.list_lessons_for_teacher(teacher_id, limit=10) if teacher_id is not None else []
        await update.effective_message.reply_text(_format_teacher_lessons(lessons), reply_markup=teacher_lessons_keyboard())
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
    if action == _CREATE_LESSON_STUDENT:
        student = _student_by_label(_student_users(context), text)
        if student is None:
            await update.effective_message.reply_text("Не нашёл такого ученика. Выберите ученика из списка.")
            return True
        context.user_data["lesson_draft"] = {"student_user_id": student["id"]}
        context.user_data["teacher_action"] = _CREATE_LESSON_TITLE
        await update.effective_message.reply_text("Введите title урока:")
        return True
    if action == _CREATE_LESSON_TITLE:
        title = text.strip()
        if not title:
            await update.effective_message.reply_text("Title не может быть пустым. Введите title урока:")
            return True
        context.user_data.setdefault("lesson_draft", {})["title"] = title
        context.user_data["teacher_action"] = _CREATE_LESSON_THEME
        await update.effective_message.reply_text("Введите theme или '-' чтобы пропустить:")
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
        context.user_data["impersonated_user_id"] = student["id"]
        context.user_data.pop("training", None)
        await update.effective_message.reply_text(
            f"👀 Режим ученика: {student['display_name']}. Действия выполняются как выбранный ученик.",
            reply_markup=main_menu_keyboard(include_exit_student_mode=True),
        )
        return True

    return False
