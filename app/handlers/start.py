from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.auth.roles import is_user_allowed
from app.config import Settings
from app.database import Database
from app.keyboards import main_menu_keyboard


def normalize_username(username: str | None) -> str:
    return (username or "").lstrip("@").casefold()


async def require_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    if tg_user is None:
        return None
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    user = db.get_user_by_telegram_id(tg_user.id)
    if user is not None:
        return user
    username = normalize_username(tg_user.username)
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
    await update.effective_message.reply_text(
        f"Привет, {user['display_name']}! Выберите действие в меню.",
        reply_markup=main_menu_keyboard(),
    )
