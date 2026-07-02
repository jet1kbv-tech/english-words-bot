from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver
from app.config import Settings
from app.database import Database
from app.handlers.training import _today_moscow
from app.keyboards import ADMIN_MENU, ADMIN_STUDENT_VIEW, ADMIN_TEACHER_VIEW, ADMIN_USERS, ADMIN_MY_MENU, EXIT_STUDENT_MODE, admin_menu_keyboard, main_menu_keyboard, teacher_menu_keyboard
from app.handlers.teacher import _student_by_label, _student_keyboard, _student_users

_SELECT_ADMIN_STUDENT = "admin_select_student"


def _resolver(context: ContextTypes.DEFAULT_TYPE) -> RoleResolver:
    settings: Settings = context.application.bot_data["settings"]
    return RoleResolver(settings)


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user is not None and _resolver(context).role_for(user.username) is Role.ADMIN


def _format_all_users(context: ContextTypes.DEFAULT_TYPE) -> str:
    db: Database = context.application.bot_data["db"]
    users = db.list_users()
    if not users:
        return "Пользователей пока нет."
    resolver = _resolver(context)
    today = _today_moscow()
    lines = ["📊 Все пользователи:"]
    for user in users:
        activity = db.get_daily_activity(user["id"], today)
        streak = activity["streak_days"] if activity else 0
        role = resolver.role_for(user["username"]).value
        username = user["username"] or "—"
        lines.append(
            f"• @{username} — {user['display_name']} | role: {role} | words: {db.count_words(user['id'])} | streak: {streak}"
        )
    return "\n".join(lines)


async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("admin_action", None)
    context.user_data.pop("admin_teacher_view", None)
    if update.effective_message:
        await update.effective_message.reply_text("🛠 Админ меню:", reply_markup=admin_menu_keyboard())


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_message is None or not is_admin(update, context):
        return False
    text = update.effective_message.text or ""

    if text == EXIT_STUDENT_MODE:
        context.user_data.pop("impersonated_user_id", None)
        context.user_data.pop("admin_action", None)
        context.user_data.pop("training", None)
        await update.effective_message.reply_text("Вы вышли из режима ученика.", reply_markup=admin_menu_keyboard())
        return True

    if context.user_data.get("impersonated_user_id"):
        return False

    if text == ADMIN_MENU:
        await show_admin_menu(update, context)
        return True
    if text == ADMIN_MY_MENU:
        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_teacher_view", None)
        await update.effective_message.reply_text("Ваше меню:", reply_markup=main_menu_keyboard(include_admin=True))
        return True
    if text == ADMIN_USERS:
        await update.effective_message.reply_text(_format_all_users(context), reply_markup=admin_menu_keyboard())
        return True
    if text == ADMIN_TEACHER_VIEW:
        context.user_data.pop("admin_action", None)
        context.user_data["admin_teacher_view"] = True
        await update.effective_message.reply_text("Teacher-view включён для admin.", reply_markup=teacher_menu_keyboard())
        return True
    if text == ADMIN_STUDENT_VIEW:
        students = _student_users(context)
        if not students:
            await update.effective_message.reply_text("Пока нет учеников для выбора.", reply_markup=admin_menu_keyboard())
            return True
        context.user_data["admin_action"] = _SELECT_ADMIN_STUDENT
        await update.effective_message.reply_text("Выберите ученика:", reply_markup=_student_keyboard(students, back_label=ADMIN_MENU))
        return True

    if context.user_data.get("admin_action") == _SELECT_ADMIN_STUDENT:
        student = _student_by_label(_student_users(context), text)
        if student is None:
            await update.effective_message.reply_text("Не нашёл такого ученика. Выберите ученика из списка.")
            return True
        context.user_data.pop("admin_action", None)
        context.user_data.pop("admin_teacher_view", None)
        context.user_data["impersonated_user_id"] = student["id"]
        context.user_data.pop("training", None)
        await update.effective_message.reply_text(
            f"👨‍🎓 Режим ученика: {student['display_name']}. Действия выполняются как выбранный ученик.",
            reply_markup=main_menu_keyboard(include_exit_student_mode=True),
        )
        return True

    return False
