from __future__ import annotations

import random

from telegram import Update
from telegram.ext import ContextTypes

from app.database import Database
from app.handlers.start import require_user
from app.keyboards import answer_keyboard, main_menu_keyboard, training_keyboard

EN_TO_RU = "EN_TO_RU"
RU_TO_EN = "RU_TO_EN"
CARD_DIRECTIONS = (EN_TO_RU, RU_TO_EN)


def card_weight(progress_score: int | None) -> int:
    if progress_score is None:
        return 5
    if progress_score <= 0:
        return 4
    if progress_score == 1:
        return 3
    if progress_score == 2:
        return 2
    return 1


def _weighted_word_order(words: list) -> list:
    remaining = list(words)
    ordered = []
    while remaining:
        weights = [card_weight(word["progress_score"]) for word in remaining]
        selected = random.choices(remaining, weights=weights, k=1)[0]
        ordered.append(selected)
        remaining.remove(selected)
    return ordered


def _session(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("training", {})


def _card_direction(session: dict, index: int) -> str:
    directions = session.setdefault("directions", [])
    while len(directions) <= index:
        directions.append(random.choice(CARD_DIRECTIONS))
    return directions[index]


def _format_answer(word: dict, direction: str, prefix: str | None = None, extra_status: str | None = None) -> str:
    if direction == EN_TO_RU:
        answer = f"{word['english']} — {word['translation']}"
    else:
        answer = f"{word['translation']} — {word['english']}"

    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(f"Ответ:\n{answer}")
    if word["example"]:
        parts.append(f"Example: {word['example']}")
    if extra_status:
        parts.append(extra_status)
    return "\n\n".join(parts)


async def start_training(update: Update, context: ContextTypes.DEFAULT_TYPE, only_mine: bool) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.list_training_words(user["id"])
    if not words:
        await update.effective_message.reply_text("Пока нет слов для тренировки. Сначала добавьте слово.", reply_markup=main_menu_keyboard())
        return
    words = _weighted_word_order(words)
    context.user_data["training"] = {
        "words": words,
        "directions": [random.choice(CARD_DIRECTIONS) for _ in words],
        "index": 0,
        "exchange": False,
    }
    await send_current_card(update, context)


async def start_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.list_partner_training_words(user["id"])
    if not words:
        await update.effective_message.reply_text("Пока нет слов партнёра для обмена.", reply_markup=main_menu_keyboard())
        return
    words = _weighted_word_order(words)
    context.user_data["training"] = {
        "words": words,
        "directions": [random.choice(CARD_DIRECTIONS) for _ in words],
        "index": 0,
        "exchange": True,
    }
    await send_current_card(update, context)


async def send_current_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _session(context)
    words = session.get("words", [])
    index = session.get("index", 0)
    if index >= len(words):
        context.user_data.pop("training", None)
        await update.effective_message.reply_text("Тренировка завершена: карточки закончились.", reply_markup=main_menu_keyboard())
        return
    word = words[index]
    direction = _card_direction(session, index)
    prompt = word["english"] if direction == EN_TO_RU else word["translation"]
    direction_text = "🇬🇧 → 🇷🇺" if direction == EN_TO_RU else "🇷🇺 → 🇬🇧"
    await update.effective_message.reply_text(
        f"Карточка {index + 1}/{len(words)}\n\n{direction_text}\nПереведи:\n{prompt}",
        reply_markup=training_keyboard(exchange=session.get("exchange", False)),
    )


async def show_translation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _session(context)
    words = session.get("words", [])
    index = session.get("index", 0)
    if not words or index >= len(words):
        await update.effective_message.reply_text("Активной тренировки нет.", reply_markup=main_menu_keyboard())
        return
    word = words[index]
    direction = _card_direction(session, index)
    text = _format_answer(word, direction)
    await update.effective_message.reply_text(text, reply_markup=training_keyboard(exchange=session.get("exchange", False)))


async def mark_card(update: Update, context: ContextTypes.DEFAULT_TYPE, remembered: bool | None) -> None:
    user = await require_user(update, context)
    session = _session(context)
    words = session.get("words", [])
    index = session.get("index", 0)
    if user is None or update.effective_message is None:
        return
    if not words or index >= len(words):
        await update.effective_message.reply_text("Активной тренировки нет.", reply_markup=main_menu_keyboard())
        return
    word = words[index]
    db: Database = context.application.bot_data["db"]
    if db.fetchone("SELECT 1 FROM words WHERE id = ?", (word["id"],)) is None:
        session["index"] = index + 1
        await update.effective_message.reply_text("Эта карточка была удалена, пропускаем её.")
        await send_current_card(update, context)
        return
    db.update_progress(user["id"], word["id"], remembered)
    session["index"] = index + 1
    if remembered is None:
        await update.effective_message.reply_text("Пропускаем ⏭")
        await send_current_card(update, context)
        return

    direction = _card_direction(session, index)
    is_exchange = session.get("exchange", False)
    if remembered is True:
        prefix = "✅ Знаю" if is_exchange else "✅ Помню"
        status = None
    else:
        prefix = "❌ Не знаю" if is_exchange else "❌ Не помню"
        status = None
        if is_exchange:
            copied = db.copy_word_to_user(word["id"], user["id"])
            status = "Добавил слово в твой словарь" if copied else "Это слово уже есть в твоём словаре"

    text = _format_answer(word, direction, prefix=prefix, extra_status=status)
    await update.effective_message.reply_text(text, reply_markup=answer_keyboard())


async def stop_training(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("training", None)
    await update.effective_message.reply_text("Тренировка остановлена.", reply_markup=main_menu_keyboard())


async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    summary = db.progress_summary(user["id"])
    await update.effective_message.reply_text(
        "Ваш прогресс:\n"
        f"• добавлено слов: {db.count_words(user['id'])}\n"
        f"• всего доступно слов: {db.count_words()}\n"
        f"• карточек тренировали: {summary['trained_cards']}\n"
        f"• средний score: {summary['average_score']:.2f}",
        reply_markup=main_menu_keyboard(),
    )
