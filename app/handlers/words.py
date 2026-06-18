from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.database import Database
from app.handlers.start import require_user
from app.keyboards import main_menu_keyboard

ENGLISH, TRANSLATION, TOPIC, EXAMPLE, BULK_WORDS = range(5)

BULK_LINE_PATTERN = re.compile(r"^(.+?)\s*(?:—|–|-|:|=)\s*(.+)$")


def format_word(row, index: int, show_owner: bool) -> str:
    parts = [f"{index}. {row['english']} — {row['translation']}"]
    if row["topic"]:
        parts.append(f"тема: {row['topic']}")
    if row["example"]:
        parts.append(f"пример: {row['example']}")
    if show_owner:
        parts.append(f"автор: {row['owner_name']}")
    return "\n".join(parts)


def delete_word_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_word:{word_id}")]])


def confirm_delete_word_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_word:{word_id}")],
            [InlineKeyboardButton("↩️ Отмена", callback_data=f"cancel_delete_word:{word_id}")],
        ]
    )


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
    added = db.add_word(user["id"], data["english"], data["translation"], data.get("topic"), None if text in {"", "-"} else text)
    message = "Готово! Слово добавлено в ваш словарь." if added else "Такое слово уже есть в вашем словаре. Дубль не добавлен."
    await update.effective_message.reply_text(message, reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def cancel_add_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_word", None)
    context.user_data.pop("bulk_words", None)
    await update.effective_message.reply_text("Добавление слова отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def bulk_add_words_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await require_user(update, context) is None or update.effective_message is None:
        return ConversationHandler.END
    await update.effective_message.reply_text(
        "Отправьте список слов, по одному на строку, в формате:\n"
        "english — translation\nenglish - translation\nenglish: translation\nenglish = translation"
    )
    return BULK_WORDS


def parse_bulk_word_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line:
        return None
    match = BULK_LINE_PATTERN.match(line)
    if match is None:
        return None
    english, translation = (part.strip() for part in match.groups())
    if not english or not translation:
        return None
    return english, translation


async def bulk_words_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return ConversationHandler.END
    db: Database = context.application.bot_data["db"]
    added = skipped = duplicates = 0
    seen_in_message: set[str] = set()
    for line in (update.effective_message.text or "").splitlines():
        parsed = parse_bulk_word_line(line)
        if parsed is None:
            if line.strip():
                skipped += 1
            continue
        english, translation = parsed
        key = english.casefold()
        if key in seen_in_message:
            duplicates += 1
            continue
        seen_in_message.add(key)
        if db.add_word(user["id"], english, translation, None, None):
            added += 1
        else:
            duplicates += 1
    await update.effective_message.reply_text(
        f"Добавлено: {added}\nПропущено: {skipped}\nДубли: {duplicates}",
        reply_markup=main_menu_keyboard(),
    )
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
    await update.effective_message.reply_text(f"{title}:", reply_markup=main_menu_keyboard())
    for index, word in enumerate(words[:50], start=1):
        await update.effective_message.reply_text(
            format_word(word, index, show_owner=not only_mine),
            reply_markup=delete_word_keyboard(word["id"]) if only_mine else None,
        )


async def delete_word_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = await require_user(update, context)
    if query is None or user is None:
        return
    await query.answer()
    word_id = int(query.data.split(":", maxsplit=1)[1])
    db: Database = context.application.bot_data["db"]
    word = db.get_owned_word(word_id, user["id"])
    if word is None:
        await query.edit_message_text("Слово не найдено или недоступно для удаления.")
        return
    await query.edit_message_text(
        f"Удалить слово {word['english']} — {word['translation']}?",
        reply_markup=confirm_delete_word_keyboard(word_id),
    )


async def confirm_delete_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = await require_user(update, context)
    if query is None or user is None:
        return
    await query.answer()
    word_id = int(query.data.split(":", maxsplit=1)[1])
    deleted = context.application.bot_data["db"].delete_word(word_id, user["id"])
    await query.edit_message_text("Слово удалено" if deleted else "Слово не найдено или недоступно для удаления.")


async def cancel_delete_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text("Удаление отменено.")
