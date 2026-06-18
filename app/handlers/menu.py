from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.training import mark_card, send_current_card, show_progress, show_translation, start_exchange, start_game_session, start_training, stop_training
from app.handlers.words import show_dictionary
from app.keyboards import DONT_KNOW, FORGET, GAME_SESSION, KNOW, MY_CARDS, NEXT_CARD, MY_WORDS, PROGRESS, REMEMBER, SHOW_TRANSLATION, SKIP, STOP, WORD_EXCHANGE, main_menu_keyboard


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    text = update.effective_message.text
    if text == MY_WORDS:
        await show_dictionary(update, context)
    elif text == WORD_EXCHANGE:
        await start_exchange(update, context)
    elif text == MY_CARDS:
        await start_training(update, context, only_mine=True)
    elif text == GAME_SESSION:
        await start_game_session(update, context)
    elif text == SHOW_TRANSLATION:
        await show_translation(update, context)
    elif text in {REMEMBER, KNOW}:
        await mark_card(update, context, remembered=True)
    elif text in {FORGET, DONT_KNOW}:
        await mark_card(update, context, remembered=False)
    elif text == SKIP:
        await mark_card(update, context, remembered=None)
    elif text == NEXT_CARD:
        await send_current_card(update, context)
    elif text == STOP:
        await stop_training(update, context)
    elif text == PROGRESS:
        await show_progress(update, context)
    else:
        await update.effective_message.reply_text("Не понял команду. Выберите действие в меню.", reply_markup=main_menu_keyboard())
