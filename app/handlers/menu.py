from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.keyboards import ALL_CARDS, ALL_WORDS, FORGET, MY_CARDS, MY_WORDS, PROGRESS, REMEMBER, SHOW_TRANSLATION, SKIP, STOP, main_menu_keyboard
from app.handlers.training import mark_card, show_progress, show_translation, start_training, stop_training
from app.handlers.words import show_dictionary


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    text = update.effective_message.text
    if text == MY_WORDS:
        await show_dictionary(update, context, only_mine=True)
    elif text == ALL_WORDS:
        await show_dictionary(update, context, only_mine=False)
    elif text == MY_CARDS:
        await start_training(update, context, only_mine=True)
    elif text == ALL_CARDS:
        await start_training(update, context, only_mine=False)
    elif text == SHOW_TRANSLATION:
        await show_translation(update, context)
    elif text == REMEMBER:
        await mark_card(update, context, remembered=True)
    elif text == FORGET:
        await mark_card(update, context, remembered=False)
    elif text == SKIP:
        await mark_card(update, context, remembered=None)
    elif text == STOP:
        await stop_training(update, context)
    elif text == PROGRESS:
        await show_progress(update, context)
    else:
        await update.effective_message.reply_text("Не понял команду. Выберите действие в меню.", reply_markup=main_menu_keyboard())
