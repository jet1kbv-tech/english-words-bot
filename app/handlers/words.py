from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from app.database import Database
from app.handlers.start import require_user
from app.keyboards import main_menu_keyboard

ENGLISH, TRANSLATION, TOPIC, EXAMPLE = range(4)


def format_word(row, index: int, show_owner: bool) -> str:
    parts = [f"{index}. {row['english']} — {row['translation']}"]
    if row["topic"]:
        parts.append(f"тема: {row['topic']}")
    if row["example"]:
        parts.append(f"пример: {row['example']}")
    if show_owner:
        parts.append(f"автор: {row['owner_name']}")
    return "\n".join(parts)


async def add_word_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await require_user(update, context) is None or update.effective_message is None:
        return ConversationHandler.END
    context.user_data["new_word"] = {}
    await update.effective_message.reply_text("Введите английское слово или фразу:")
    return ENGLISH


async def english_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    if not text:
        await update.effective_message.reply_text("Слово не должно быть пустым. Введите английское слово или фразу:")
        return ENGLISH
    context.user_data["new_word"]["english"] = text
    await update.effective_message.reply_text("Введите перевод:")
    return TRANSLATION


async def translation_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    if not text:
        await update.effective_message.reply_text("Перевод не должен быть пустым. Введите перевод:")
        return TRANSLATION
    context.user_data["new_word"]["translation"] = text
    await update.effective_message.reply_text("Введите тему или отправьте '-' если темы нет:")
    return TOPIC


async def topic_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.effective_message.text or "").strip()
    context.user_data["new_word"]["topic"] = None if text in {"", "-"} else text
    await update.effective_message.reply_text("Введите пример или отправьте '-' если примера нет:")
    return EXAMPLE


async def example_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return ConversationHandler.END
    text = (update.effective_message.text or "").strip()
    data = context.user_data.pop("new_word", {})
    db: Database = context.application.bot_data["db"]
    db.add_word(user["id"], data["english"], data["translation"], data.get("topic"), None if text in {"", "-"} else text)
    await update.effective_message.reply_text("Готово! Слово добавлено в ваш словарь.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def cancel_add_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_word", None)
    await update.effective_message.reply_text("Добавление слова отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def show_dictionary(update: Update, context: ContextTypes.DEFAULT_TYPE, only_mine: bool) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.list_words(user["id"] if only_mine else None)
    title = "Ваш словарь" if only_mine else "Общий словарь"
    if not words:
        await update.effective_message.reply_text(f"{title} пока пуст.", reply_markup=main_menu_keyboard())
        return
    chunks = [title + ":"]
    for index, word in enumerate(words, start=1):
        chunks.append(format_word(word, index, show_owner=not only_mine))
    await update.effective_message.reply_text("\n\n".join(chunks[:51]), reply_markup=main_menu_keyboard())
