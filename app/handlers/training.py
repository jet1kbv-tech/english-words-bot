from __future__ import annotations

import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from app.database import Database
from app.ai.service import check_text_answer
from app.handlers.start import require_user
from app.keyboards import answer_keyboard, main_menu_keyboard, text_input_keyboard, training_keyboard

EN_TO_RU = "EN_TO_RU"
RU_TO_EN = "RU_TO_EN"
CARD_DIRECTIONS = (EN_TO_RU, RU_TO_EN)
GAME_SESSION_SIZE = 10
SELF_CHECK = "self_check"
TEXT_INPUT = "text_input"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


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


def build_game_session_words(words: list, limit: int = GAME_SESSION_SIZE) -> list:
    """Pick a short mix: mostly new/weak cards plus a few strong cards."""
    new_words = [word for word in words if word["progress_score"] is None]
    weak_words = [word for word in words if word["progress_score"] is not None and word["progress_score"] <= 2]
    strong_words = [word for word in words if word["progress_score"] is not None and word["progress_score"] > 2]

    random.shuffle(new_words)
    weak_words = _weighted_word_order(weak_words)
    random.shuffle(strong_words)

    strong_quota = max(1, limit // 5)
    primary_quota = limit - strong_quota
    selected = (new_words + weak_words)[:primary_quota]
    selected.extend(strong_words[:strong_quota])

    if len(selected) < limit:
        selected_ids = {word["id"] for word in selected}
        fallback = [word for word in _weighted_word_order(words) if word["id"] not in selected_ids]
        selected.extend(fallback[: limit - len(selected)])

    random.shuffle(selected)
    return selected[:limit]



def _word_int(word: dict, key: str, default: int = 0) -> int:
    value = word[key] if key in word.keys() else default
    return default if value is None else int(value)


def _is_mistake_word(word: dict) -> bool:
    score = word["progress_score"] if "progress_score" in word.keys() else None
    if score is not None and int(score) <= 1:
        return True
    return _word_int(word, "times_forgotten") > _word_int(word, "times_remembered")


def _mistake_severity(word: dict) -> tuple[int, int, int]:
    score = word["progress_score"] if "progress_score" in word.keys() else None
    forgotten = _word_int(word, "times_forgotten")
    remembered = _word_int(word, "times_remembered")
    score_priority = 100 if score is None else max(0, 10 - int(score))
    return (forgotten - remembered, forgotten, score_priority)


def build_mistake_session_words(words: list, limit: int = GAME_SESSION_SIZE) -> list:
    """Pick a game session focused on the user's weakest personal words."""
    mistake_words = [word for word in words if _is_mistake_word(word)]
    mistake_words.sort(key=_mistake_severity, reverse=True)

    selected = mistake_words[:limit]
    if len(selected) < limit:
        selected_ids = {word["id"] for word in selected}
        fallback_pool = [word for word in words if word["id"] not in selected_ids]
        selected.extend(build_game_session_words(fallback_pool, limit - len(selected)))

    random.shuffle(selected)
    return selected[:limit]

def _session(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.user_data.setdefault("training", {})


def _card_direction(session: dict, index: int) -> str:
    directions = session.setdefault("directions", [])
    while len(directions) <= index:
        directions.append(random.choice(CARD_DIRECTIONS))
    return directions[index]


def _normalize_answer(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()


def _translation_variants(translation: str) -> list[str]:
    return [part for part in (_normalize_answer(part) for part in re.split(r"[/,;]", translation)) if part]


def _is_text_answer_correct(word: dict, direction: str, answer: str) -> bool:
    normalized_answer = _normalize_answer(answer)
    if direction == RU_TO_EN:
        return normalized_answer == _normalize_answer(word["english"])
    return normalized_answer in _translation_variants(word["translation"])


def _format_full_answer(word: dict, prefix: str | None = None) -> str:
    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(f"Ответ:\n{word['english']} — {word['translation']}")
    if word["example"]:
        parts.append(f"Example: {word['example']}")
    return "\n\n".join(parts)


def _sync_game_counters(session: dict) -> None:
    session["known"] = int(session.get("remembered_count", session.get("known", 0)))
    session["unknown"] = int(session.get("forgotten_count", session.get("unknown", 0)))


def _increment_game_counter(session: dict, key: str, delta: int = 1) -> None:
    alias = "known" if key == "remembered_count" else "unknown"
    session[key] = max(int(session.get(key, session.get(alias, 0))) + delta, 0)
    session[alias] = session[key]


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


def _today_moscow() -> str:
    return datetime.now(MOSCOW_TZ).date().isoformat()


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
        "game": False,
    }
    await send_current_card(update, context)


async def start_game_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.list_training_words(user["id"])
    if not words:
        await update.effective_message.reply_text("Пока нет слов для игры. Сначала добавьте слово.", reply_markup=main_menu_keyboard())
        return
    words = build_game_session_words(words)
    session_id = db.start_study_session(user["id"], len(words))
    context.user_data["training"] = {
        "words": words,
        "directions": [random.choice(CARD_DIRECTIONS) for _ in words],
        "index": 0,
        "exchange": False,
        "game": True,
        "session_id": session_id,
        "known": 0,
        "unknown": 0,
        "remembered_count": 0,
        "forgotten_count": 0,
        "skipped": 0,
    }
    await update.effective_message.reply_text("🎮 Игра на 10 слов начинается!", reply_markup=text_input_keyboard())
    await send_current_card(update, context)


async def start_mistakes_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    words = db.list_training_words(user["id"])
    if not words:
        await update.effective_message.reply_text("Пока нет слов для разбора ошибок. Сначала добавьте слово.", reply_markup=main_menu_keyboard())
        return
    words = build_mistake_session_words(words)
    session_id = db.start_study_session(user["id"], len(words))
    context.user_data["training"] = {
        "words": words,
        "directions": [random.choice(CARD_DIRECTIONS) for _ in words],
        "index": 0,
        "exchange": False,
        "game": True,
        "mistakes": True,
        "session_id": session_id,
        "known": 0,
        "unknown": 0,
        "remembered_count": 0,
        "forgotten_count": 0,
        "skipped": 0,
    }
    await update.effective_message.reply_text("😵 Разбор ошибок начинается!", reply_markup=text_input_keyboard())
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
        "game": False,
    }
    await send_current_card(update, context)


async def _finish_game(update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict) -> None:
    db: Database = context.application.bot_data["db"]
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    _sync_game_counters(session)
    known = int(session.get("known", 0))
    unknown = int(session.get("unknown", 0))
    skipped = int(session.get("skipped", 0))
    total = len(session.get("words", []))
    if session.get("session_id"):
        db.finish_study_session(session["session_id"], known, unknown, skipped)
    activity = db.record_daily_activity(user["id"], _today_moscow(), known + unknown, known, unknown, skipped)
    context.user_data.pop("training", None)
    await update.effective_message.reply_text(
        ("😵 Разбор ошибок завершён!\n" if session.get("mistakes") else "🎮 Игра завершена!\n")
        + f"• карточек: {total}\n"
        f"• знаю: {known}\n"
        f"• не знаю: {unknown}\n"
        f"• пропущено: {skipped}\n"
        f"• streak: {activity['streak_days']} дн.\n"
        f"• уровень дня: {activity['day_level']}",
        reply_markup=main_menu_keyboard(),
    )


async def send_current_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = _session(context)
    words = session.get("words", [])
    index = session.get("index", 0)
    if index >= len(words):
        if session.get("game"):
            await _finish_game(update, context, session)
        else:
            context.user_data.pop("training", None)
            await update.effective_message.reply_text("Тренировка завершена: карточки закончились.", reply_markup=main_menu_keyboard())
        return
    session.pop("last_positive_answer", None)
    session.pop("last_negative_text_answer", None)
    word = words[index]
    direction = _card_direction(session, index)
    task_type = TEXT_INPUT if session.get("game") else SELF_CHECK
    session.pop("awaiting_text_input", None)
    if task_type == TEXT_INPUT:
        session["awaiting_text_input"] = {"index": index, "direction": direction}
        prompt = word["english"] if direction == EN_TO_RU else word["translation"]
        direction_text = "🇬🇧 → 🇷🇺" if direction == EN_TO_RU else "🇷🇺 → 🇬🇧"
        await update.effective_message.reply_text(
            f"Игра {index + 1}/{len(words)}\n\n✍️ Напиши ответ в чат\n{direction_text}\nПереведи:\n{prompt}",
            reply_markup=text_input_keyboard(),
        )
        return
    prompt = word["english"] if direction == EN_TO_RU else word["translation"]
    direction_text = "🇬🇧 → 🇷🇺" if direction == EN_TO_RU else "🇷🇺 → 🇬🇧"
    title = "Игра" if session.get("game") else "Карточка"
    await update.effective_message.reply_text(
        f"{title} {index + 1}/{len(words)}\n\n{direction_text}\nПереведи:\n{prompt}",
        reply_markup=training_keyboard(exchange=session.get("exchange", False), game=session.get("game", False)),
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
    await update.effective_message.reply_text(_format_answer(word, direction), reply_markup=training_keyboard(exchange=session.get("exchange", False), game=session.get("game", False)))


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
    if session.get("awaiting_text_input"):
        if session.get("game") and remembered is False:
            direction = session["awaiting_text_input"].get("direction") or _card_direction(session, index)
            db: Database = context.application.bot_data["db"]
            if db.fetchone("SELECT 1 FROM words WHERE id = ?", (word["id"],)) is None:
                session.pop("awaiting_text_input", None)
                session["index"] = index + 1
                await update.effective_message.reply_text("Эта карточка была удалена, пропускаем её.")
                await send_current_card(update, context)
                return
            db.update_progress(user["id"], word["id"], remembered=False)
            session.pop("awaiting_text_input", None)
            session.pop("last_positive_answer", None)
            session.pop("last_negative_text_answer", None)
            session["index"] = index + 1
            _increment_game_counter(session, "forgotten_count")
            await update.effective_message.reply_text(_format_full_answer(word, prefix="❌ Не знаю"), reply_markup=answer_keyboard())
            return
        await update.effective_message.reply_text("Сейчас нужно написать ответ в чат или закончить игру.", reply_markup=text_input_keyboard())
        return
    db: Database = context.application.bot_data["db"]
    if db.fetchone("SELECT 1 FROM words WHERE id = ?", (word["id"],)) is None:
        session["index"] = index + 1
        await update.effective_message.reply_text("Эта карточка была удалена, пропускаем её.")
        await send_current_card(update, context)
        return
    db.update_progress(user["id"], word["id"], remembered)
    session["index"] = index + 1
    if remembered is None:
        session.pop("last_positive_answer", None)
        session["skipped"] = int(session.get("skipped", 0)) + 1
        await update.effective_message.reply_text("Пропускаем ⏭")
        await send_current_card(update, context)
        return

    if remembered:
        _increment_game_counter(session, "remembered_count")
    else:
        _increment_game_counter(session, "forgotten_count")
        session.pop("last_positive_answer", None)

    direction = _card_direction(session, index)
    is_exchange = session.get("exchange", False)
    if remembered is True:
        prefix = "✅ Знаю" if (is_exchange or session.get("game")) else "✅ Помню"
        status = None
        session["last_positive_answer"] = {
            "word_id": word["id"],
            "index": index,
            "direction": direction,
            "exchange": bool(is_exchange),
            "game": bool(session.get("game")),
            "corrected": False,
        }
    else:
        prefix = "❌ Не знаю" if (is_exchange or session.get("game")) else "❌ Не помню"
        status = None
        if is_exchange:
            copied = db.copy_word_to_user(word["id"], user["id"])
            status = "Добавил слово в твой словарь" if copied else "Это слово уже есть в твоём словаре"

    await update.effective_message.reply_text(
        _format_answer(word, direction, prefix=prefix, extra_status=status),
        reply_markup=answer_keyboard(can_correct=remembered is True),
    )


async def correct_last_positive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    session = _session(context)
    correction = session.get("last_positive_answer")
    if user is None or update.effective_message is None:
        return
    if not correction:
        await update.effective_message.reply_text("Сейчас нечего исправлять.", reply_markup=answer_keyboard())
        return
    word_id = correction.get("word_id")
    db: Database = context.application.bot_data["db"]
    word = db.fetchone("SELECT * FROM words WHERE id = ?", (word_id,))
    if word is None:
        session.pop("last_positive_answer", None)
        await update.effective_message.reply_text("Эта карточка была удалена, исправлять нечего.", reply_markup=answer_keyboard())
        return
    if not correction.get("corrected"):
        db.correct_remembered_to_forgotten(user["id"], word_id)
        _increment_game_counter(session, "remembered_count", -1)
        _increment_game_counter(session, "forgotten_count")
        if correction.get("exchange"):
            db.copy_word_to_user(word_id, user["id"])
        correction["corrected"] = True

    direction = correction.get("direction") or _card_direction(session, int(correction.get("index", 0)))
    text = _format_answer(word, direction, prefix="Ок, исправил: отмечено как ❌ Не знаю")
    await update.effective_message.reply_text(text, reply_markup=answer_keyboard())


async def handle_text_input_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = await require_user(update, context)
    session = _session(context)
    pending = session.get("awaiting_text_input")
    words = session.get("words", [])
    index = int(session.get("index", 0))
    if not pending or user is None or update.effective_message is None or not words or index >= len(words):
        return False
    if int(pending.get("index", -1)) != index:
        session.pop("awaiting_text_input", None)
        return False

    word = words[index]
    direction = pending.get("direction") or _card_direction(session, index)
    user_answer = update.effective_message.text or ""
    ai_result = None
    if session.get("game"):
        ai_result = await check_text_answer(
            english=word["english"],
            translation=word["translation"],
            direction=direction,
            user_answer=user_answer,
        )
    remembered = ai_result.is_correct if ai_result is not None else _is_text_answer_correct(word, direction, user_answer)
    db: Database = context.application.bot_data["db"]
    db.update_progress(user["id"], word["id"], remembered)
    session.pop("awaiting_text_input", None)
    session["index"] = index + 1
    session.pop("last_positive_answer", None)

    if remembered:
        _increment_game_counter(session, "remembered_count")
        reply_markup = answer_keyboard()
        prefix = "✅ Верно"
    else:
        _increment_game_counter(session, "forgotten_count")
        session["last_negative_text_answer"] = {"word_id": word["id"], "index": index, "direction": direction, "corrected": False}
        reply_markup = answer_keyboard(can_confirm_correct=True)
        prefix = "❌ Не совсем"

    if ai_result is not None and ai_result.feedback:
        prefix = f"{prefix}\n{ai_result.feedback}"

    await update.effective_message.reply_text(_format_full_answer(word, prefix=prefix), reply_markup=reply_markup)
    return True


async def correct_last_negative_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    session = _session(context)
    correction = session.get("last_negative_text_answer")
    if user is None or update.effective_message is None:
        return
    if not correction:
        await update.effective_message.reply_text("Сейчас нечего исправлять.", reply_markup=answer_keyboard())
        return
    word_id = correction.get("word_id")
    db: Database = context.application.bot_data["db"]
    word = db.fetchone("SELECT * FROM words WHERE id = ?", (word_id,))
    if word is None:
        session.pop("last_negative_text_answer", None)
        await update.effective_message.reply_text("Эта карточка была удалена, исправлять нечего.", reply_markup=answer_keyboard())
        return
    if not correction.get("corrected"):
        db.correct_forgotten_to_remembered(user["id"], word_id)
        _increment_game_counter(session, "forgotten_count", -1)
        _increment_game_counter(session, "remembered_count")
        correction["corrected"] = True

    await update.effective_message.reply_text(_format_full_answer(word, prefix="Ок, исправил: отмечено как ✅ Знаю"), reply_markup=answer_keyboard())


async def stop_training(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.user_data.get("training")
    if session and session.get("game") and update.effective_message is not None:
        await _finish_game(update, context, session)
        return
    context.user_data.pop("training", None)
    await update.effective_message.reply_text("Тренировка остановлена.", reply_markup=main_menu_keyboard())


async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_user(update, context)
    if user is None or update.effective_message is None:
        return
    db: Database = context.application.bot_data["db"]
    summary = db.progress_summary(user["id"])
    activity = db.get_daily_activity(user["id"], _today_moscow())
    streak = activity["streak_days"] if activity else 0
    day_level = activity["day_level"] if activity else "Новичок"
    await update.effective_message.reply_text(
        "Ваш прогресс:\n"
        f"• добавлено слов: {db.count_words(user['id'])}\n"
        f"• всего доступно слов: {db.count_words()}\n"
        f"• карточек тренировали: {summary['trained_cards']}\n"
        f"• средний score: {summary['average_score']:.2f}\n"
        f"• streak: {streak} дн.\n"
        f"• уровень дня: {day_level}",
        reply_markup=main_menu_keyboard(),
    )


async def daily_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    for user in db.list_users():
        await context.bot.send_message(
            chat_id=user["telegram_id"],
            text="⏰ Время короткой практики: сыграйте 🎮 Игру на 10 слов и продлите streak!",
            reply_markup=main_menu_keyboard(),
        )
