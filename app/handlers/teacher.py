from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.database import Database
from app.handlers.start import IMPERSONATION_KEY, clear_impersonation, is_teacher_username, require_user, student_mode_keyboard
from app.handlers.training import _today_moscow
from app.keyboards import teacher_menu_keyboard


def _is_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings: Settings = context.application.bot_data['settings']
    username = update.effective_user.username if update.effective_user else None
    return is_teacher_username(settings, username)


async def require_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await require_user(update, context)
    if user is None:
        return None
    if not _is_teacher(update, context):
        if update.effective_message:
            await update.effective_message.reply_text('Эта команда доступна только учителю.')
        return None
    return user


def student_entries(settings: Settings) -> list[tuple[str, str]]:
    usernames = sorted(settings.allowed_usernames - settings.teacher_usernames)
    return [(username, settings.display_names.get(username, username)) for username in usernames]


def students_keyboard(settings: Settings, prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(name, callback_data=f'{prefix}:{username}')] for username, name in student_entries(settings)])


async def show_teacher_students(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_teacher(update, context) is None or update.effective_message is None:
        return
    settings: Settings = context.application.bot_data['settings']
    students = student_entries(settings)
    lines = ['👤 Ученики', '', *(f'• {name}' for _, name in students)]
    if not students:
        lines.append('Пока нет настроенных учеников.')
    await update.effective_message.reply_text('\n'.join(lines), reply_markup=students_keyboard(settings, 'teacher_student'))


async def show_add_word_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_teacher(update, context) is None or update.effective_message is None:
        return
    await update.effective_message.reply_text('Скоро здесь можно будет добавлять слова ученику.', reply_markup=teacher_menu_keyboard())


async def choose_student_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_teacher(update, context) is None or update.effective_message is None:
        return
    settings: Settings = context.application.bot_data['settings']
    await update.effective_message.reply_text('Кого показать в режиме ученика?', reply_markup=students_keyboard(settings, 'teacher_view_as'))


async def exit_student_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    clear_impersonation(context)
    await update.effective_message.reply_text('Вы вышли из режима ученика.', reply_markup=teacher_menu_keyboard())


async def choose_student_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_teacher(update, context) is None or update.effective_message is None:
        return
    settings: Settings = context.application.bot_data['settings']
    await update.effective_message.reply_text('Выберите ученика:', reply_markup=students_keyboard(settings, 'teacher_progress'))


def _format_student_progress(name: str, progress: dict) -> str:
    weak_words = progress['weak_words']
    lines = [
        f'📊 Прогресс ученика: {name}',
        f'• всего слов: {progress["total_words"]}',
        f'• карточек сегодня: {progress["cards_today"]}',
        f'• XP сегодня: {progress["xp_today"]}',
        f'• streak: {progress["streak"]} дн.',
        '• слабые слова top-10:',
    ]
    if not weak_words:
        lines.append('  — пока нет данных')
    else:
        for index, word in enumerate(weak_words, start=1):
            lines.append(f'  {index}. {word["english"]} — {word["translation"]} (score {word["score"]})')
    return '\n'.join(lines)


async def teacher_progress_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if await require_teacher(update, context) is None:
        return
    username = query.data.split(':', maxsplit=1)[1]
    settings: Settings = context.application.bot_data['settings']
    name = dict(student_entries(settings)).get(username, username)
    db: Database = context.application.bot_data['db']
    student = db.get_user_by_username(username)
    if student is None:
        await query.edit_message_text(f'📊 Прогресс ученика: {name}\n\nУченик ещё не запускал /start.')
        return
    progress = db.student_progress(student['id'], _today_moscow())
    await query.edit_message_text(_format_student_progress(name, progress))


async def teacher_student_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if await require_teacher(update, context) is None:
        return
    username = query.data.split(':', maxsplit=1)[1]
    settings: Settings = context.application.bot_data['settings']
    name = dict(student_entries(settings)).get(username, username)
    await query.edit_message_text(f'👤 Ученик: {name}\n\nЧтобы посмотреть прогресс, выберите «📊 Прогресс ученика» в меню учителя.')


async def teacher_view_as_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if await require_teacher(update, context) is None:
        return
    username = query.data.split(':', maxsplit=1)[1]
    settings: Settings = context.application.bot_data['settings']
    name = dict(student_entries(settings)).get(username, username)
    db: Database = context.application.bot_data['db']
    student = db.get_user_by_username(username)
    if student is None:
        await query.edit_message_text(f'Нельзя включить режим ученика: {name} ещё не запускал /start.')
        return
    context.user_data[IMPERSONATION_KEY] = {'username': username, 'display_name': name}
    await query.message.reply_text(
        f'👀 Вы в режиме ученика: {name}\nВсе действия будут выполняться как этот ученик.',
        reply_markup=student_mode_keyboard(context),
    )
