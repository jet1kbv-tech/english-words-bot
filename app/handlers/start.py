from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.database import Database
from app.keyboards import main_menu_keyboard, teacher_menu_keyboard

IMPERSONATION_KEY = "impersonated_student"


def is_teacher_username(settings: Settings, username: str | None) -> bool:
    return normalize_username(username) in settings.teacher_usernames


def user_main_menu(settings: Settings, username: str | None):
    return teacher_menu_keyboard() if is_teacher_username(settings, username) else main_menu_keyboard()


def is_impersonating_student(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return IMPERSONATION_KEY in context.user_data


def impersonation_label(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    student = context.user_data.get(IMPERSONATION_KEY)
    return student["display_name"] if student else None


def student_mode_keyboard(context: ContextTypes.DEFAULT_TYPE):
    return main_menu_keyboard(include_exit_student_mode=is_impersonating_student(context))


def clear_impersonation(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(IMPERSONATION_KEY, None)


def normalize_username(username: str | None) -> str:
    return (username or "").lstrip("@").lower()


async def require_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    if tg_user is None:
        return None
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    username = normalize_username(tg_user.username)
    impersonated = context.user_data.get(IMPERSONATION_KEY)
    if impersonated and is_teacher_username(settings, username):
        student = db.get_user_by_username(impersonated["username"])
        if student is not None:
            return student
        context.user_data.pop(IMPERSONATION_KEY, None)
        if update.effective_message:
            await update.effective_message.reply_text("Режим ученика сброшен: ученик не найден.", reply_markup=teacher_menu_keyboard())
        return None

    user = db.get_user_by_telegram_id(tg_user.id)
    if user is not None:
        return user
    if username not in settings.allowed_usernames:
        if update.effective_message:
            await update.effective_message.reply_text("Извините, этот бот доступен только Вове, Саше и настроенным учителям.")
        return None
    display_name = settings.display_names.get(username) or tg_user.full_name or username
    return db.upsert_user(tg_user.id, username, display_name)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    if tg_user is None or update.effective_message is None:
        return
    clear_impersonation(context)
    settings: Settings = context.application.bot_data["settings"]
    username = normalize_username(tg_user.username)
    existing_user = context.application.bot_data["db"].get_user_by_telegram_id(tg_user.id)
    if existing_user is None and username not in settings.allowed_usernames:
        await update.effective_message.reply_text("Извините, доступ разрешён только @wp_bvv, @privetnormalno и настроенным учителям.")
        return

    stored_username = username or existing_user["username"]
    display_name = existing_user["display_name"] if existing_user else settings.display_names.get(stored_username) or tg_user.full_name or stored_username
    user = context.application.bot_data["db"].upsert_user(tg_user.id, stored_username, display_name)
    menu_title = "👩‍🏫 Учитель" if is_teacher_username(settings, user["username"]) else "главное меню"
    await update.effective_message.reply_text(
        f"Привет, {user['display_name']}! Выберите действие в меню: {menu_title}.",
        reply_markup=user_main_menu(settings, user["username"]),
    )
