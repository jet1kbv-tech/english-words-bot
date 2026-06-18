from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from app.database import Database
from app.handlers.start import require_user
from app.keyboards import answer_keyboard, main_menu_keyboard, training_keyboard

EN_TO_RU = "EN_TO_RU"
RU_TO_EN = "RU_TO_EN"
CARD_DIRECTIONS = (EN_TO_RU, RU_TO_EN)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
GAME_LIMIT = 10


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
    words = db.list_words(user["id"])
    if not words:
        await update.effective_message.reply_text("Пока нет слов для тренировки. Сначала добавьте слово.", reply_markup=main_menu_keyboard())
        return
    random.shuffle(words)
    context.user_data["training"] = {
        "words": words,
        "directions": [random.choice(CARD_DIRECTIONS) for _ in words],
        "index": 0,
        "exchange": False,
    }
    await send_current_card(update, context)


async def start_game_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.select_game_words(user["id"], GAME_LIMIT)
    if not words:
        await update.effective_message.reply_text("Пока нет слов для игры. Сначала добавьте слово.", reply_markup=main_menu_keyboard())
        return
    session_id = db.create_study_session(user["id"], len(words))
    context.user_data["training"] = {
        "words": words,
        "directions": [random.choice(CARD_DIRECTIONS) for _ in words],
        "index": 0,
        "exchange": False,
        "game": True,
        "study_session_id": session_id,
        "remembered_count": 0,
        "forgotten_count": 0,
        "skipped_count": 0,
    }
    await send_current_card(update, context)


async def start_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.list_partner_words(user["id"])
    if not words:
        await update.effective_message.reply_text("Пока нет слов партнёра для обмена.", reply_markup=main_menu_keyboard())
        return
    random.shuffle(words)
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
        if session.get("game"):
            await finish_game_session(update, context, completed=True)
            return
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
    if session.get("game"):
        if remembered is True:
            session["remembered_count"] = session.get("remembered_count", 0) + 1
        elif remembered is False:
            session["forgotten_count"] = session.get("forgotten_count", 0) + 1
        else:
            session["skipped_count"] = session.get("skipped_count", 0) + 1
    session["index"] = index + 1
    if remembered is None and not session.get("game"):
        await update.effective_message.reply_text("Пропускаем ⏭")
        await send_current_card(update, context)
        return

    direction = _card_direction(session, index)
    is_exchange = session.get("exchange", False)
    if remembered is True:
        prefix = "✅ Знаю" if (is_exchange or session.get("game")) else "✅ Помню"
        status = None
    elif remembered is False:
        prefix = "❌ Не знаю" if (is_exchange or session.get("game")) else "❌ Не помню"
        status = None
        if is_exchange:
            copied = db.copy_word_to_user(word["id"], user["id"])
            status = "Добавил слово в твой словарь" if copied else "Это слово уже есть в твоём словаре"
    else:
        prefix = "⏭ Пропущено"
        status = None

    text = _format_answer(word, direction, prefix=prefix, extra_status=status)
    await update.effective_message.reply_text(text, reply_markup=answer_keyboard())


def _day_level(sessions_completed: int) -> str:
    if sessions_completed <= 1:
        return "Разогреватель слов"
    if sessions_completed == 2:
        return "Уверенный словожор"
    if sessions_completed == 3:
        return "Лексический зверь"
    return "Повелитель карточек"


def _plural_days(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return "день"
    if 2 <= days % 10 <= 4 and not 12 <= days % 100 <= 14:
        return "дня"
    return "дней"


async def finish_game_session(update: Update, context: ContextTypes.DEFAULT_TYPE, completed: bool) -> None:
    user = await require_user(update, context)
    session = _session(context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    remembered = session.get("remembered_count", 0)
    forgotten = session.get("forgotten_count", 0)
    skipped = session.get("skipped_count", 0)
    reviewed = remembered + forgotten + skipped
    db.finish_study_session(session["study_session_id"], remembered, forgotten, skipped, completed)
    context.user_data.pop("training", None)
    if not completed:
        await update.effective_message.reply_text("Игра остановлена.", reply_markup=main_menu_keyboard())
        return

    today = datetime.now(MOSCOW_TZ).date()
    activity = db.update_daily_activity(user["id"], today, reviewed)
    streak = db.current_streak(user["id"], today)
    await update.effective_message.reply_text(
        "🎉 Сессия завершена!\n\n"
        f"📚 Карточек в сессии: {reviewed}\n"
        f"✅ Знаю: {remembered}\n"
        f"❌ Не знаю: {forgotten}\n"
        f"⏭ Пропущено: {skipped}\n\n"
        "Сегодня:\n"
        f"🎮 Сессий: {activity['sessions_completed']}\n"
        f"📚 Карточек: {activity['cards_reviewed']}\n"
        f"🔥 Streak: {streak} {_plural_days(streak)} подряд\n\n"
        f"Уровень дня: {_day_level(activity['sessions_completed'])}",
        reply_markup=main_menu_keyboard(),
    )


async def stop_training(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _session(context)
    if session.get("game"):
        await finish_game_session(update, context, completed=False)
        return
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
