from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver, is_user_allowed
from app.config import Settings
from app.database import Database
from app.keyboards import main_menu_keyboard, teacher_menu_keyboard


def normalize_username(username: str | None) -> str:
    return (username or "").lstrip("@").casefold()


async def require_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    if tg_user is None:
        return None
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    username = normalize_username(tg_user.username)
    resolver = RoleResolver(settings)
    impersonated_user_id = context.user_data.get("impersonated_user_id")
    if impersonated_user_id and resolver.role_for(username) in {Role.TEACHER, Role.ADMIN}:
        impersonated_user = db.get_user_by_id(int(impersonated_user_id))
        if impersonated_user is not None:
            return impersonated_user
        context.user_data.pop("impersonated_user_id", None)

    user = db.get_user_by_telegram_id(tg_user.id)
    if user is not None:
        return user
    if not is_user_allowed(username, settings):
        if update.effective_message:
            await update.effective_message.reply_text("Извините, этот бот доступен только Вове и Саше.")
        return None
    return db.upsert_user(tg_user.id, username, settings.display_names.get(username, username))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_user = update.effective_user
    if tg_user is None or update.effective_message is None:
        return
    settings: Settings = context.application.bot_data["settings"]
    username = normalize_username(tg_user.username)
    existing_user = context.application.bot_data["db"].get_user_by_telegram_id(tg_user.id)
    if existing_user is None and not is_user_allowed(username, settings):
        await update.effective_message.reply_text("Извините, доступ разрешён только @wp_bvv и @privetnormalno.")
        return

    display_name = existing_user["display_name"] if existing_user else settings.display_names.get(username, username)
    user = context.application.bot_data["db"].upsert_user(tg_user.id, username or existing_user["username"], display_name)
    resolver = RoleResolver(settings)
    role = resolver.role_for(username)
    if role is Role.TEACHER:
        context.user_data.pop("impersonated_user_id", None)
        reply_markup = teacher_menu_keyboard()
        message = f"Привет, {user['display_name']}! Выберите действие в teacher menu."
    else:
        context.user_data.pop("admin_teacher_view", None)
        context.user_data.pop("impersonated_user_id", None)
        reply_markup = main_menu_keyboard(include_admin=role is Role.ADMIN)
        message = f"Привет, {user['display_name']}! Выберите действие в меню."
    await update.effective_message.reply_text(message, reply_markup=reply_markup)
