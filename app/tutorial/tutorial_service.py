from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

from app.database import Database
from app.keyboards import HELP, HELP_GETTING_STARTED
from app.tutorial.tutorial_models import Tutorial
from app.tutorial.tutorial_registry import get_tutorial, tutorial_for_role

TUTORIAL_STATE = "tutorial_state"
TUTORIAL_NEXT = "➡️ Далее"
TUTORIAL_BACK = "⬅️ Назад"
TUTORIAL_FINISH = "🏁 Завершить"
TUTORIAL_CLOSE = "❌ Закрыть"
HELP_BACK = "⬅️ Назад"


def role_tutorial_key(role: str) -> str | None:
    tutorial = tutorial_for_role(role)
    return tutorial.key if tutorial else None


def should_start_first_run(db: Database, user_id: int, role: str) -> bool:
    key = role_tutorial_key(role)
    return bool(key and not db.has_completed_tutorial(user_id, key))


def format_help_screen() -> str:
    return "❓ Помощь\n\nВыберите раздел:"


def help_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(HELP_GETTING_STARTED)], [KeyboardButton(HELP_BACK)]], resize_keyboard=True)


def tutorial_keyboard(step_index: int, total: int) -> ReplyKeyboardMarkup:
    rows = []
    nav = []
    if step_index > 0:
        nav.append(KeyboardButton(TUTORIAL_BACK))
    nav.append(KeyboardButton(TUTORIAL_FINISH if step_index == total - 1 else TUTORIAL_NEXT))
    rows.append(nav)
    rows.append([KeyboardButton(TUTORIAL_CLOSE)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def format_tutorial_step(tutorial: Tutorial, step_index: int) -> str:
    if step_index < 0 or step_index >= len(tutorial.steps):
        step_index = 0
    step = tutorial.steps[step_index]
    return f"{tutorial.title}\n\nШаг {step_index + 1} из {len(tutorial.steps)}\n\n{step.text}"


def start_tutorial_state(context, tutorial_key: str, *, first_run: bool) -> Tutorial | None:
    tutorial = get_tutorial(tutorial_key)
    if tutorial is None:
        return None
    context.user_data[TUTORIAL_STATE] = {"key": tutorial_key, "step": 0, "first_run": first_run}
    return tutorial


def current_tutorial(context) -> tuple[Tutorial, int, bool] | None:
    state = context.user_data.get(TUTORIAL_STATE) or {}
    tutorial = get_tutorial(str(state.get("key") or ""))
    if tutorial is None:
        context.user_data.pop(TUTORIAL_STATE, None)
        return None
    step = int(state.get("step") or 0)
    if step < 0 or step >= len(tutorial.steps):
        step = 0
        state["step"] = 0
    return tutorial, step, bool(state.get("first_run"))


def clear_tutorial(context) -> None:
    context.user_data.pop(TUTORIAL_STATE, None)
