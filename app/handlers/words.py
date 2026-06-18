from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.database import Database
from app.handlers.start import require_user
from app.keyboards import main_menu_keyboard

ENGLISH, TRANSLATION, TOPIC, EXAMPLE, BULK_WORDS = range(5)

BULK_LINE_PATTERN = re.compile(r"^(.+?)\s*(?:—|–|-|:|=)\s*(.+)$")


WORDS_PAGE_SIZE = 10


def format_word(row, index: int, show_owner: bool = False) -> str:
    line = f"{index}. {row['english']} — {row['translation']}"
    extras = []
    if row["topic"]:
        extras.append(f"тема: {row['topic']}")
    if row["example"]:
        extras.append(f"пример: {row['example']}")
    if show_owner:
        extras.append(f"автор: {row['owner_name']}")
    return line if not extras else f"{line}\n   " + "; ".join(extras)


def dictionary_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅️ Назад", callback_data=f"dict_page:{max(page - 1, 0)}"),
                InlineKeyboardButton("➡️ Далее", callback_data=f"dict_page:{min(page + 1, total_pages - 1)}"),
            ],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"dict_delete_page:{page}")],
            [InlineKeyboardButton("↩️ В меню", callback_data="dict_menu")],
        ]
    )


def delete_page_keyboard(words: list, page: int) -> InlineKeyboardMarkup:
    rows = []
    for offset, word in enumerate(words, start=1):
        rows.append([InlineKeyboardButton(f"🗑 {offset}", callback_data=f"dict_delete_word:{page}:{word['id']}")])
    rows.append([InlineKeyboardButton("↩️ Назад", callback_data=f"dict_page:{page}")])
    rows.append([InlineKeyboardButton("↩️ В меню", callback_data="dict_menu")])
    return InlineKeyboardMarkup(rows)


def confirm_delete_word_keyboard(word_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_word:{page}:{word_id}")],
            [InlineKeyboardButton("↩️ Отмена", callback_data=f"dict_delete_page:{page}")],
        ]
    )


def build_dictionary_page(words: list, page: int) -> tuple[str, InlineKeyboardMarkup]:
    total_pages = max((len(words) + WORDS_PAGE_SIZE - 1) // WORDS_PAGE_SIZE, 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * WORDS_PAGE_SIZE
    page_words = words[start : start + WORDS_PAGE_SIZE]
    lines = ["📚 Мой словарь", f"Страница {page + 1} из {total_pages}", ""]
    lines.extend(format_word(word, start + offset) for offset, word in enumerate(page_words, start=1))
    return "\n".join(lines), dictionary_keyboard(page, total_pages)


def _dictionary_words(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list:
    db: Database = context.application.bot_data["db"]
    words = db.list_words(user_id)
    context.user_data["dictionary_words"] = [word["id"] for word in words]
    return words


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


async def show_dictionary(update: Update, context: ContextTypes.DEFAULT_TYPE, only_mine: bool = True) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    words = _dictionary_words(context, user["id"])
    if not words:
        await update.effective_message.reply_text("📚 Мой словарь пока пуст.", reply_markup=main_menu_keyboard())
        return
    text, keyboard = build_dictionary_page(words, 0)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def dictionary_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = await require_user(update, context)
    if query is None or user is None:
        return
    await query.answer()
    page = int(query.data.split(":", maxsplit=1)[1])
    words = _dictionary_words(context, user["id"])
    if not words:
        await query.edit_message_text("📚 Мой словарь пока пуст.")
        return
    text, keyboard = build_dictionary_page(words, page)
    await query.edit_message_text(text, reply_markup=keyboard)


async def dictionary_delete_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = await require_user(update, context)
    if query is None or user is None:
        return
    await query.answer()
    page = int(query.data.split(":", maxsplit=1)[1])
    words = _dictionary_words(context, user["id"])
    if not words:
        await query.edit_message_text("📚 Мой словарь пока пуст.")
        return
    total_pages = max((len(words) + WORDS_PAGE_SIZE - 1) // WORDS_PAGE_SIZE, 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * WORDS_PAGE_SIZE
    page_words = words[start : start + WORDS_PAGE_SIZE]
    lines = ["Выберите слово для удаления:", ""]
    lines.extend(format_word(word, start + offset) for offset, word in enumerate(page_words, start=1))
    await query.edit_message_text("\n".join(lines), reply_markup=delete_page_keyboard(page_words, page))


async def delete_word_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = await require_user(update, context)
    if query is None or user is None:
        return
    await query.answer()
    _, page_text, word_id_text = query.data.split(":", maxsplit=2)
    page = int(page_text)
    word_id = int(word_id_text)
    words = _dictionary_words(context, user["id"])
    start = page * WORDS_PAGE_SIZE
    current_page_ids = {word["id"] for word in words[start : start + WORDS_PAGE_SIZE]}
    if word_id not in current_page_ids:
        await query.edit_message_text("Это слово уже не находится на текущей странице словаря.")
        return
    db: Database = context.application.bot_data["db"]
    word = db.get_owned_word(word_id, user["id"])
    if word is None:
        await query.edit_message_text("Слово не найдено или недоступно для удаления.")
        return
    await query.edit_message_text(
        f"Удалить слово {word['english']} — {word['translation']}?",
        reply_markup=confirm_delete_word_keyboard(word_id, page),
    )


async def confirm_delete_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = await require_user(update, context)
    if query is None or user is None:
        return
    await query.answer()
    _, page_text, word_id_text = query.data.split(":", maxsplit=2)
    page = int(page_text)
    word_id = int(word_id_text)
    deleted = context.application.bot_data["db"].delete_word(word_id, user["id"])
    words = _dictionary_words(context, user["id"])
    if not deleted:
        await query.edit_message_text("Слово не найдено или недоступно для удаления.")
        return
    if not words:
        await query.edit_message_text("Слово удалено.\n\n📚 Мой словарь теперь пуст.")
        return
    text, keyboard = build_dictionary_page(words, page)
    await query.edit_message_text(f"Слово удалено.\n\n{text}", reply_markup=keyboard)


async def dictionary_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text("Вернулись в меню.")
    if update.effective_message:
        await update.effective_message.reply_text("Выберите действие:", reply_markup=main_menu_keyboard())


async def cancel_delete_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dictionary_menu(update, context)
