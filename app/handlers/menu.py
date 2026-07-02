from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver
from app.config import Settings
from app.database import Database
from app.handlers.training import correct_last_negative_text_answer, correct_last_positive_answer, handle_text_input_answer, mark_card, send_current_card, show_progress, show_translation, start_exchange, start_game_session, start_mistakes_session, start_training, stop_training
from app.handlers.words import show_dictionary
from app.handlers.admin import handle_admin_message
from app.handlers.teacher import handle_teacher_message
from app.handlers.student_lessons import handle_student_lesson_message
from app.keyboards import DONT_KNOW, FORGET, GAME_SESSION, HELP, HELP_GETTING_STARTED, I_WAS_RIGHT, MY_MISTAKES, KNOW, MISTAKE, MY_CARDS, NEXT_CARD, MY_WORDS, PROGRESS, REMEMBER, SHOW_TRANSLATION, SKIP, STOP, WORD_EXCHANGE, main_menu_keyboard, teacher_menu_keyboard
from app.tutorial.tutorial_service import HELP_BACK, TUTORIAL_BACK, TUTORIAL_CLOSE, TUTORIAL_FINISH, TUTORIAL_NEXT, clear_tutorial, current_tutorial, format_help_screen, format_tutorial_step, help_keyboard, role_tutorial_key, start_tutorial_state, tutorial_keyboard


def _role_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user = update.effective_user
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    role = RoleResolver(settings, db).role_for(user.username if user else None)
    if role is Role.ADMIN and context.user_data.get("admin_teacher_view"):
        return "TEACHER"
    return role.name


def _role_menu(role_name: str):
    return teacher_menu_keyboard() if role_name == "TEACHER" else main_menu_keyboard(include_admin=role_name == "ADMIN")


async def _finish_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE, *, completed: bool) -> bool:
    current = current_tutorial(context)
    if current is None or update.effective_message is None:
        return False
    tutorial, _step, first_run = current
    if completed and first_run and update.effective_user is not None:
        db: Database = context.application.bot_data["db"]
        user = db.get_user_by_telegram_id(update.effective_user.id)
        if user is not None:
            db.mark_tutorial_completed(int(user["id"]), user["username"], tutorial.key)
    clear_tutorial(context)
    role_name = _role_name(update, context)
    await update.effective_message.reply_text("Готово!", reply_markup=_role_menu(role_name))
    return True


async def handle_tutorial_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_message is None:
        return False
    text = update.effective_message.text or ""
    current = current_tutorial(context)
    if current is None:
        return False
    tutorial, step, _first_run = current
    if text == TUTORIAL_CLOSE:
        return await _finish_tutorial(update, context, completed=False)
    if text == TUTORIAL_BACK:
        step = max(0, step - 1)
    elif text == TUTORIAL_NEXT:
        step = min(len(tutorial.steps) - 1, step + 1)
    elif text == TUTORIAL_FINISH:
        return await _finish_tutorial(update, context, completed=True)
    else:
        step = 0
    context.user_data["tutorial_state"]["step"] = step
    await update.effective_message.reply_text(format_tutorial_step(tutorial, step), reply_markup=tutorial_keyboard(step, len(tutorial.steps)))
    return True


async def handle_help_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_message is None:
        return False
    text = update.effective_message.text or ""
    if text == HELP:
        await update.effective_message.reply_text(format_help_screen(), reply_markup=help_keyboard())
        return True
    if text == HELP_GETTING_STARTED:
        key = role_tutorial_key(_role_name(update, context))
        tutorial = start_tutorial_state(context, key, first_run=False) if key else None
        if tutorial is None:
            await update.effective_message.reply_text("Для этой роли обучение пока недоступно.")
            return True
        await update.effective_message.reply_text(format_tutorial_step(tutorial, 0), reply_markup=tutorial_keyboard(0, len(tutorial.steps)))
        return True
    if text == HELP_BACK:
        role_name = _role_name(update, context)
        await update.effective_message.reply_text("Выберите действие в меню.", reply_markup=_role_menu(role_name))
        return True
    return False


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    text = update.effective_message.text
    if await handle_tutorial_message(update, context):
        return
    if await handle_help_message(update, context):
        return
    if await handle_admin_message(update, context):
        return
    if await handle_teacher_message(update, context):
        return
    if await handle_student_lesson_message(update, context):
        return
    if text == MY_WORDS:
        await show_dictionary(update, context)
    elif text == WORD_EXCHANGE:
        await start_exchange(update, context)
    elif text == MY_CARDS:
        await start_training(update, context, only_mine=True)
    elif text == GAME_SESSION:
        await start_game_session(update, context)
    elif text == MY_MISTAKES:
        await start_mistakes_session(update, context)
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
        await update.effective_message.reply_text("Не понял команду. Выберите действие в меню.", reply_markup=main_menu_keyboard())
