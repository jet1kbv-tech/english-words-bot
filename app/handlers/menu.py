from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.training import correct_last_negative_text_answer, correct_last_positive_answer, handle_text_input_answer, mark_card, send_current_card, show_progress, show_translation, start_exchange, start_game_session, start_training, stop_training
from app.handlers.start import impersonation_label, student_mode_keyboard
from app.handlers.teacher import choose_student_mode, choose_student_progress, exit_student_mode, show_add_word_placeholder, show_teacher_students
from app.handlers.words import show_dictionary
from app.keyboards import DONT_KNOW, EXIT_STUDENT_MODE, FORGET, GAME_SESSION, I_WAS_RIGHT, KNOW, MISTAKE, MY_CARDS, NEXT_CARD, MY_WORDS, PROGRESS, REMEMBER, SHOW_TRANSLATION, SKIP, STOP, TEACHER_ADD_WORD, TEACHER_PROGRESS, TEACHER_STUDENTS, TEACHER_VIEW_AS_STUDENT, WORD_EXCHANGE, main_menu_keyboard


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    text = update.effective_message.text
    if text == EXIT_STUDENT_MODE:
        await exit_student_mode(update, context)
    elif label := impersonation_label(context):
        await update.effective_message.reply_text(f"👀 Вы в режиме ученика: {label}", reply_markup=student_mode_keyboard(context))
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
        elif text == MISTAKE:
            await correct_last_positive_answer(update, context)
        elif text == I_WAS_RIGHT:
            await correct_last_negative_text_answer(update, context)
        elif text == STOP:
            await stop_training(update, context)
        elif text == PROGRESS:
            await show_progress(update, context)
        else:
            if await handle_text_input_answer(update, context):
                return
            await update.effective_message.reply_text("Не понял команду. Выберите действие в меню.", reply_markup=student_mode_keyboard(context))
    elif text == MY_WORDS:
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
    elif text == MISTAKE:
        await correct_last_positive_answer(update, context)
    elif text == I_WAS_RIGHT:
        await correct_last_negative_text_answer(update, context)
    elif text == STOP:
        await stop_training(update, context)
    elif text == PROGRESS:
        await show_progress(update, context)
    elif text == TEACHER_STUDENTS:
        await show_teacher_students(update, context)
    elif text == TEACHER_ADD_WORD:
        await show_add_word_placeholder(update, context)
    elif text == TEACHER_PROGRESS:
        await choose_student_progress(update, context)
    elif text == TEACHER_VIEW_AS_STUDENT:
        await choose_student_mode(update, context)
    else:
        if await handle_text_input_answer(update, context):
            return
        await update.effective_message.reply_text("Не понял команду. Выберите действие в меню.", reply_markup=main_menu_keyboard())
