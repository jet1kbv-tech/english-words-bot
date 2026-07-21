from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.auth.roles import Role, RoleResolver
from app.config import Settings
from app.database import Database
from app.ai.service import generate_word_translations
from app.handlers.training import _today_moscow
from app.keyboards import ADD_STUDENT, EXIT_STUDENT_MODE, TEACHER_CREATE_LESSON, TEACHER_IMPERSONATE, TEACHER_LESSONS, TEACHER_MY_LESSONS, TEACHER_PROGRESS, TEACHER_STUDENTS, main_menu_keyboard, teacher_lessons_keyboard, teacher_menu_keyboard
from app.lesson_metadata import lesson_display_name
from app.notifications.notification_service import NotificationService
from app.lesson_repository import LessonRepository
from app.lesson_service import HomeworkTaskError, LessonService, LessonWordImportError, normalize_lesson_words_import
from app.student_access_service import StudentAccessService

_SELECT_PROGRESS = "teacher_select_progress"
_SELECT_IMPERSONATE = "teacher_select_impersonate"
_CREATE_LESSON_STUDENT = "teacher_create_lesson_student"
_CREATE_LESSON_TITLE = "teacher_create_lesson_title"
_CREATE_LESSON_THEME = "teacher_create_lesson_theme"
_CREATE_LESSON_GRAMMAR = "teacher_create_lesson_grammar"
_OPTIONAL_SKIP = {"", "-", "пропустить", "skip"}
_ADD_STUDENT = "teacher_add_student"
_IMPORT_LESSON_WORDS = "teacher_import_lesson_words"
_EDIT_LESSON_WORD = "teacher_edit_lesson_word"
_EDIT_AI_TRANSLATION_DRAFT = "edit_ai_translation_draft"
_PENDING_WORD_EDIT = "pending_lesson_word_edit"
_PENDING_LESSON_WORDS = "pending_lesson_words"
_PENDING_AI_TRANSLATION = "pending_ai_translation"
_PENDING_AI_TRANSLATION_EDIT = "pending_ai_translation_edit"
_SELECTED_LESSON_WORDS = "selected_lesson_words"
_CREATE_HOMEWORK_TASK = "teacher_create_homework_task"
_PENDING_HOMEWORK_TASK = "pending_homework_task"
_REVIEW_HOMEWORK_ANSWER = "teacher_review_homework_answer"
_PENDING_HOMEWORK_REVIEW = "pending_homework_review"
NOT_STARTED_TEXT = "Ученик ещё не запускал бота. Попросите его открыть бота и нажать /start."

HOMEWORK_TASK_TYPE_LABELS = {
    "translation": "📝 Перевод",
    "free": "✍️ Свободный ответ",
    "quiz": "🔘 Тест",
}

LESSON_BACK_TO_LIST = "⬅️ К списку уроков"
TEACHER_LESSONS_BACK = "⬅️ Назад"
TEACHER_LESSON_OPEN_PREFIX = "Урок "
TEACHER_LESSON_WORDS_PREFIX = "teacher:lesson:words:"
TEACHER_LESSON_GRAMMAR_PREFIX = "teacher:lesson:grammar:"
TEACHER_LESSON_EXERCISES_PREFIX = "teacher:lesson:exercises:"
TEACHER_LESSON_HOMEWORK_PREFIX = "teacher:lesson:homework:"
TEACHER_LESSON_AI_PREFIX = "teacher:lesson:ai:"
TEACHER_LESSON_BACK_PREFIX = "teacher:lesson:back:"
TEACHER_LESSON_ASSIGN_PREFIX = "teacher:lesson:assign:"
TEACHER_LESSON_ASSIGN_STUDENT_PREFIX = "teacher:lesson:assign_student:"
TEACHER_LESSON_UNASSIGN_PREFIX = "teacher:lesson:unassign:"
TEACHER_LESSON_WORDS_ADD_PREFIX = "teacher:lesson:words:add:"
TEACHER_LESSON_WORDS_SELECT_PREFIX = "teacher:lesson:words:select:"
TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX = "teacher:lesson:words:select:toggle:"
TEACHER_LESSON_WORDS_SELECT_ALL_PREFIX = "teacher:lesson:words:select:all:"
TEACHER_LESSON_WORDS_SELECT_CLEAR_PREFIX = "teacher:lesson:words:select:clear:"
TEACHER_LESSON_WORDS_SELECT_DONE_PREFIX = "teacher:lesson:words:select:done:"
TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX = "teacher:lesson:words:ai_translate:"
TEACHER_LESSON_WORDS_AI_APPLY_PREFIX = "teacher:lesson:words:ai_apply:"
TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX = "teacher:lesson:words:ai_cancel:"
TEACHER_LESSON_WORDS_AI_EDIT_PREFIX = "teacher:lesson:words:ai_edit:"
TEACHER_LESSON_WORDS_AI_PREVIEW_PREFIX = "teacher:lesson:words:ai_preview:"
TEACHER_LESSON_WORD_OPEN_PREFIX = "teacher:lesson:word:open:"
TEACHER_LESSON_WORDS_CONFIRM_PREFIX = "teacher:lesson:words:confirm:"
TEACHER_LESSON_WORDS_CANCEL_PREFIX = "teacher:lesson:words:cancel:"
TEACHER_LESSON_WORD_EDIT_PREFIX = "teacher:lesson:word:edit:"
TEACHER_LESSON_HOMEWORK_ADD_PREFIX = "teacher:lesson:homework:add:"
TEACHER_LESSON_HOMEWORK_ADD_TYPE_PREFIX = "teacher:lesson:homework:add_type:"
TEACHER_LESSON_HOMEWORK_CANCEL_PREFIX = "teacher:lesson:homework:cancel:"
TEACHER_LESSON_HOMEWORK_OPEN_PREFIX = "teacher:lesson:homework:open:"
TEACHER_LESSON_HOMEWORK_DELETE_PREFIX = "teacher:lesson:homework:delete:"
TEACHER_LESSON_HOMEWORK_DELETE_CONFIRM_PREFIX = "teacher:lesson:homework:delete_confirm:"
TEACHER_LESSON_HOMEWORK_REVIEW_CORRECT_PREFIX = "teacher:lesson:homework:review_correct:"
TEACHER_LESSON_HOMEWORK_REVIEW_INCORRECT_PREFIX = "teacher:lesson:homework:review_incorrect:"
TEACHER_LESSONS_LIST_CALLBACK = "teacher:lessons:list"
TEACHER_LESSON_CALLBACK_PREFIXES = (
    TEACHER_LESSON_WORDS_PREFIX,
    TEACHER_LESSON_GRAMMAR_PREFIX,
    TEACHER_LESSON_EXERCISES_PREFIX,
    TEACHER_LESSON_HOMEWORK_PREFIX,
    TEACHER_LESSON_AI_PREFIX,
    TEACHER_LESSON_BACK_PREFIX,
    TEACHER_LESSON_ASSIGN_STUDENT_PREFIX,
    TEACHER_LESSON_ASSIGN_PREFIX,
    TEACHER_LESSON_UNASSIGN_PREFIX,
    TEACHER_LESSON_WORDS_ADD_PREFIX,
    TEACHER_LESSON_WORDS_CONFIRM_PREFIX,
    TEACHER_LESSON_WORDS_CANCEL_PREFIX,
    TEACHER_LESSON_WORD_OPEN_PREFIX,
    TEACHER_LESSON_WORD_EDIT_PREFIX,
    TEACHER_LESSON_WORDS_AI_EDIT_PREFIX,
    TEACHER_LESSON_WORDS_AI_PREVIEW_PREFIX,
)


def _lesson_service(db: Database) -> LessonService:
    return LessonService(LessonRepository(db))


def _status_label(status: str) -> str:
    return status[:1].upper() + status[1:].lower()


def _format_lessons_screen(lessons: list) -> str:
    if not lessons:
        return "📚 Уроки\n\nПока нет уроков.\n\nСоздайте первый урок."
    lines = ["📚 Уроки", ""]
    for index, lesson in enumerate(lessons, start=1):
        lines.append(f"{index}. {lesson_display_name(lesson)} — {_status_label(lesson['status'])}")
    return "\n".join(lines)


def _lessons_list_keyboard(lessons: list) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(f"Урок {lesson['id']}")] for lesson in lessons]
    rows.append([KeyboardButton(TEACHER_CREATE_LESSON)])
    rows.append([KeyboardButton(TEACHER_LESSONS_BACK)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _count(summary, key: str) -> int:
    return int(summary[key] or 0) if key in summary.keys() else 0


def _optional_summary_value(summary, key: str) -> str:
    if hasattr(summary, "keys") and key in summary.keys() and summary[key]:
        return str(summary[key])
    return "—"


def _format_lesson_detail(summary, assignment=None) -> str:
    student = f"@{assignment['student_username']}" if assignment is not None else "—"
    return "\n".join([
        "📚 Урок",
        "",
        f"Урок: {lesson_display_name(summary)}",
        f"Статус: {_status_label(summary['status'])}",
        "",
        f"Тема: {_optional_summary_value(summary, 'topic')}",
        f"Уровень: {_optional_summary_value(summary, 'level')}",
        f"Описание: {_optional_summary_value(summary, 'description')}",
        "",
        "👤 Ученик",
        "",
        student,
        "",
        f"📖 Слова: {_count(summary, 'words_count')}",
        f"📝 Грамматика: {_count(summary, 'grammar_count')}",
        f"✏️ Упражнения: {_count(summary, 'exercises_count')}",
        f"🏠 Домашнее задание: {_count(summary, 'homework_count')}",
    ])


def _lesson_detail_keyboard(lesson_id: int, assignment=None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📖 Слова", callback_data=f"{TEACHER_LESSON_WORDS_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("📝 Грамматика", callback_data=f"{TEACHER_LESSON_GRAMMAR_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("✏️ Упражнения", callback_data=f"{TEACHER_LESSON_EXERCISES_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("🏠 Домашнее задание", callback_data=f"{TEACHER_LESSON_HOMEWORK_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("🤖 AI-помощник", callback_data=f"{TEACHER_LESSON_AI_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("👤 Назначить ученика", callback_data=f"{TEACHER_LESSON_ASSIGN_PREFIX}{lesson_id}")],
    ]
    if assignment is not None:
        rows.append([InlineKeyboardButton("❌ Снять назначение", callback_data=f"{TEACHER_LESSON_UNASSIGN_PREFIX}{lesson_id}")])
    rows.append([InlineKeyboardButton(LESSON_BACK_TO_LIST, callback_data=TEACHER_LESSONS_LIST_CALLBACK)])
    return InlineKeyboardMarkup(rows)





def _format_assign_student_screen(summary, students: list) -> str:
    if not students:
        return "Нет доступных учеников."
    return "\n".join(["Выберите ученика для урока:", "", lesson_display_name(summary)])

def _assign_student_keyboard(lesson_id: int, students: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"@{student['username']}", callback_data=f"{TEACHER_LESSON_ASSIGN_STUDENT_PREFIX}{lesson_id}:{student['username']}")] for student in students]
    rows.append([InlineKeyboardButton("⬅️ Lesson", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")])
    return InlineKeyboardMarkup(rows)

def _assign_student_ids_from_callback(data: str) -> tuple[int, str] | None:
    payload = data.removeprefix(TEACHER_LESSON_ASSIGN_STUDENT_PREFIX).strip()
    lesson_id_text, sep, username = payload.partition(":")
    if sep != ":" or not lesson_id_text.isdigit() or not username.strip():
        return None
    return int(lesson_id_text), username

def _format_lesson_words(words: list) -> str:
    if not words:
        return "📖 Слова\n\nВ этом уроке пока нет слов."
    lines = ["📖 Слова", "", f"Всего слов: {len(words)}", ""]
    lines.extend(f"• {word['text']}" for word in words)
    return "\n".join(lines)


def _lesson_words_keyboard(lesson_id: int, words: list | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(str(word["text"]), callback_data=f"{TEACHER_LESSON_WORD_OPEN_PREFIX}{lesson_id}:{word['word_id']}")]
        for word in (words or [])[:20]
    ]
    if words:
        rows.append([InlineKeyboardButton("☑️ Выбрать", callback_data=f"{TEACHER_LESSON_WORDS_SELECT_PREFIX}{lesson_id}")])
    rows.extend([
        [InlineKeyboardButton("➕ Добавить слова", callback_data=f"{TEACHER_LESSON_WORDS_ADD_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("⬅️ Урок", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")],
    ])
    return InlineKeyboardMarkup(rows)


def _selected_lesson_words(context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> set[int]:
    selections = context.user_data.setdefault(_SELECTED_LESSON_WORDS, {})
    selected = selections.setdefault(lesson_id, set())
    if not isinstance(selected, set):
        selected = set(selected)
        selections[lesson_id] = selected
    return selected


def _actual_word_ids(words: list) -> set[int]:
    return {int(word["word_id"]) for word in words}


def _prune_lesson_words_selection(context: ContextTypes.DEFAULT_TYPE, lesson_id: int, words: list) -> set[int]:
    selected = _selected_lesson_words(context, lesson_id)
    selected.intersection_update(_actual_word_ids(words))
    return selected


def _format_lesson_words_selection(words: list, selected_word_ids: set[int]) -> str:
    if not words:
        return "📖 Слова — выбор\n\nВ этом уроке пока нет слов."
    lines = ["📖 Слова — выбор", "", f"Выбрано: {len(selected_word_ids)} из {len(words)}", ""]
    for word in words:
        mark = "☑" if int(word["word_id"]) in selected_word_ids else "☐"
        lines.append(f"{mark} {word['text']}")
    return "\n".join(lines)


def _lesson_words_selection_keyboard(lesson_id: int, words: list, selected_word_ids: set[int]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{'☑' if int(word['word_id']) in selected_word_ids else '☐'} {word['text']}",
                callback_data=f"{TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX}{lesson_id}:{word['word_id']}",
            )
        ]
        for word in words[:20]
    ]
    if selected_word_ids:
        rows.append([InlineKeyboardButton("🤖 Перевести", callback_data=f"{TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX}{lesson_id}")])
    rows.extend([
        [InlineKeyboardButton("✅ Выбрать все", callback_data=f"{TEACHER_LESSON_WORDS_SELECT_ALL_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("🧹 Очистить", callback_data=f"{TEACHER_LESSON_WORDS_SELECT_CLEAR_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("⬅️ Готово", callback_data=f"{TEACHER_LESSON_WORDS_SELECT_DONE_PREFIX}{lesson_id}")],
    ])
    return InlineKeyboardMarkup(rows)


def _optional_word_value(word, key: str) -> str:
    value = word[key] if hasattr(word, "keys") and key in word.keys() else None
    if value is None or str(value).strip() == "":
        return "—"
    return str(value)


def _format_lesson_word_detail(summary, word) -> str:
    if summary is None or word is None:
        return "Слово не найдено."
    return "\n".join([
        "📖 Слово",
        "",
        f"Урок: {lesson_display_name(summary)}",
        f"Английский: {_optional_word_value(word, 'english')}",
        f"Перевод: {_optional_word_value(word, 'translation')}",
        f"Пример: {_optional_word_value(word, 'example')}",
        f"Тема: {_optional_word_value(word, 'topic')}",
    ])


def _lesson_word_detail_keyboard(lesson_id: int, word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Перевод", callback_data=f"{TEACHER_LESSON_WORD_EDIT_PREFIX}translation:{lesson_id}:{word_id}")],
        [InlineKeyboardButton("✏️ Пример", callback_data=f"{TEACHER_LESSON_WORD_EDIT_PREFIX}example:{lesson_id}:{word_id}")],
        [InlineKeyboardButton("✏️ Тема", callback_data=f"{TEACHER_LESSON_WORD_EDIT_PREFIX}topic:{lesson_id}:{word_id}")],
        [InlineKeyboardButton("⬅️ Слова", callback_data=f"{TEACHER_LESSON_WORDS_PREFIX}{lesson_id}")],
    ])


def _format_lesson_words_preview(words: list[str]) -> str:
    return "\n".join(["Будут добавлены:", "", *(f"{index}. {word}" for index, word in enumerate(words, start=1))])


def _lesson_words_preview_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сохранить", callback_data=f"{TEACHER_LESSON_WORDS_CONFIRM_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"{TEACHER_LESSON_WORDS_CANCEL_PREFIX}{lesson_id}")],
    ])



def _format_ai_translation_preview(translations: list[dict[str, str]]) -> str:
    lines = ["Будут обновлены переводы", ""]
    for index, item in enumerate(translations, start=1):
        translation = item.get("translation") or ""
        lines.extend([f"{index}. {item['english']}", f"→ {translation}", ""])
    return "\n".join(lines).rstrip()


def _ai_translation_preview_keyboard(lesson_id: int, translations: list[dict[str, str]] | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"✏️ {item['english']}", callback_data=f"{TEACHER_LESSON_WORDS_AI_EDIT_PREFIX}{lesson_id}:{item['word_id']}")]
        for item in (translations or [])[:20]
    ]
    rows.extend([
        [InlineKeyboardButton("✅ Применить", callback_data=f"{TEACHER_LESSON_WORDS_AI_APPLY_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"{TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX}{lesson_id}")],
    ])
    return InlineKeyboardMarkup(rows)


def _ai_translation_fallback_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Слова", callback_data=f"{TEACHER_LESSON_WORDS_PREFIX}{lesson_id}")]])


def _ai_translation_missing_item_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ К предпросмотру", callback_data=f"{TEACHER_LESSON_WORDS_AI_PREVIEW_PREFIX}{lesson_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"{TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX}{lesson_id}")],
    ])


def _ai_translation_draft_for_lesson(context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> list[dict[str, str]] | None:
    draft = context.user_data.get(_PENDING_AI_TRANSLATION) or {}
    translations = draft.get("translations") if int(draft.get("lesson_id", 0)) == lesson_id else None
    return translations if isinstance(translations, list) else None


def _find_ai_translation_draft_item(translations: list[dict[str, str]], word_id: int) -> dict[str, str] | None:
    for item in translations:
        if int(item.get("word_id", 0)) == word_id:
            return item
    return None


def _clear_ai_translation_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_PENDING_AI_TRANSLATION, None)
    context.user_data.pop(_PENDING_AI_TRANSLATION_EDIT, None)
    if context.user_data.get("teacher_action") == _EDIT_AI_TRANSLATION_DRAFT:
        context.user_data.pop("teacher_action", None)


def _ai_translation_edit_ids_from_callback(data: str) -> tuple[int, int] | None:
    ids_text = data.removeprefix(TEACHER_LESSON_WORDS_AI_EDIT_PREFIX).strip()
    lesson_id_text, separator, word_id_text = ids_text.partition(":")
    if separator != ":" or not lesson_id_text.isdigit() or not word_id_text.isdigit():
        return None
    return int(lesson_id_text), int(word_id_text)


def _selected_word_rows(service: LessonService, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> list:
    words = service.list_lesson_words(lesson_id)
    selected = _prune_lesson_words_selection(context, lesson_id, words)
    rows = []
    for word in words:
        if int(word["word_id"]) in selected:
            row = service.get_lesson_word(lesson_id, int(word["word_id"]))
            if row is not None:
                rows.append(row)
    return rows

def _normalize_word_edit_value(text: str, limit: int) -> str | None:
    value = text.strip()
    if value.casefold() in {"-", "—", "пусто"}:
        return None
    if len(value) > limit:
        raise ValueError(f"Максимум {limit} символов.")
    return value


def _word_edit_limit(field: str) -> int:
    return {"translation": 500, "example": 1000, "topic": 100}[field]


def _update_word_field(db: Database, lesson_id: int, word_id: int, field: str, value: str | None) -> bool:
    if field == "translation":
        return db.update_word_translation(lesson_id, word_id, value)
    if field == "example":
        return db.update_word_example(lesson_id, word_id, value)
    if field == "topic":
        return db.update_word_topic(lesson_id, word_id, value)
    raise ValueError("unsupported word field")


def _lesson_words_prompt() -> str:
    return "Отправьте список слов.\n\nКаждое слово с новой строки.\n\nНапример\n\nreceipt\nworth it\nstale"


async def _show_lesson_words(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, *, edit: bool = False) -> None:
    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)
    words = service.list_lesson_words(lesson_id)
    text = _format_lesson_words(words)
    markup = _lesson_words_keyboard(lesson_id, words)
    if edit and update.callback_query is not None:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def _show_lesson_words_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    words = _lesson_service(db).list_lesson_words(lesson_id)
    selected_word_ids = _prune_lesson_words_selection(context, lesson_id, words)
    text = _format_lesson_words_selection(words, selected_word_ids)
    markup = _lesson_words_selection_keyboard(lesson_id, words, selected_word_ids)
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text, reply_markup=markup)


def _format_lesson_section(summary, section: str) -> str:
    descriptions = {
        "words": ("📖 Слова", "Этот раздел скоро позволит добавлять и редактировать слова урока."),
        "grammar": ("📝 Грамматика", "Этот раздел скоро позволит добавлять грамматическую тему и объяснения."),
        "exercises": ("✏️ Упражнения", "Этот раздел скоро позволит добавлять упражнения урока."),
        "ai": ("🤖 AI-помощник", "Скоро здесь можно будет сгенерировать слова, упражнения, домашку и подсказки с помощью AI."),
    }
    title, description = descriptions[section]
    return "\n".join([title, "", description, "", f"Урок: {lesson_display_name(summary)}"])


def _lesson_section_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К уроку", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")]])


def _homework_task_label(task) -> str:
    icon_label = HOMEWORK_TASK_TYPE_LABELS.get(str(task["task_type"]), str(task["task_type"]))
    prompt = str(task["prompt"])
    short_prompt = prompt if len(prompt) <= 60 else prompt[:57] + "…"
    return f"{icon_label}: {short_prompt}"


def _answer_status_icon(answer) -> str:
    if answer is None:
        return "⚪"
    is_correct = answer["is_correct"] if hasattr(answer, "keys") and "is_correct" in answer.keys() else None
    if is_correct is None:
        return "⏳"
    return "✅" if is_correct else "❌"


def _answer_status_label(answer) -> str:
    is_correct = answer["is_correct"] if hasattr(answer, "keys") and "is_correct" in answer.keys() else None
    if is_correct is None:
        return "⏳ На проверке"
    return "✅ Верно" if is_correct else "❌ Неверно"


def _format_lesson_homework(summary, tasks: list, answers: dict | None = None) -> str:
    header = ["🏠 Домашнее задание", "", f"Урок: {lesson_display_name(summary)}"]
    if not tasks:
        return "\n".join(header + ["", "Пока нет заданий."])
    answers = answers or {}
    lines = [
        f"{index}. {_answer_status_icon(answers.get(int(task['id'])))} {_homework_task_label(task)}"
        for index, task in enumerate(tasks, start=1)
    ]
    return "\n".join(header + [""] + lines)


def _lesson_homework_keyboard(lesson_id: int, tasks: list, answers: dict | None = None) -> InlineKeyboardMarkup:
    answers = answers or {}
    rows = [
        [InlineKeyboardButton(
            f"{_answer_status_icon(answers.get(int(task['id'])))} {_homework_task_label(task)}",
            callback_data=f"{TEACHER_LESSON_HOMEWORK_OPEN_PREFIX}{lesson_id}:{task['id']}",
        )]
        for task in tasks
    ]
    rows.append([InlineKeyboardButton("➕ Добавить задание", callback_data=f"{TEACHER_LESSON_HOMEWORK_ADD_PREFIX}{lesson_id}")])
    rows.append([InlineKeyboardButton("⬅️ Урок", callback_data=f"{TEACHER_LESSON_BACK_PREFIX}{lesson_id}")])
    return InlineKeyboardMarkup(rows)


def _homework_type_picker_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(HOMEWORK_TASK_TYPE_LABELS["translation"], callback_data=f"{TEACHER_LESSON_HOMEWORK_ADD_TYPE_PREFIX}translation:{lesson_id}")],
        [InlineKeyboardButton(HOMEWORK_TASK_TYPE_LABELS["free"], callback_data=f"{TEACHER_LESSON_HOMEWORK_ADD_TYPE_PREFIX}free:{lesson_id}")],
        [InlineKeyboardButton(HOMEWORK_TASK_TYPE_LABELS["quiz"], callback_data=f"{TEACHER_LESSON_HOMEWORK_ADD_TYPE_PREFIX}quiz:{lesson_id}")],
        [InlineKeyboardButton("⬅️ Отмена", callback_data=f"{TEACHER_LESSON_HOMEWORK_CANCEL_PREFIX}{lesson_id}")],
    ])


def _optional_task_value(task, key: str) -> str:
    value = task[key] if hasattr(task, "keys") and key in task.keys() else None
    if value is None or str(value).strip() == "":
        return "—"
    return str(value)


def _format_homework_task_detail(summary, task, answer=None) -> str:
    if summary is None or task is None:
        return "Задание не найдено."
    task_type = str(task["task_type"])
    lines = [
        "🏠 Задание",
        "",
        f"Урок: {lesson_display_name(summary)}",
        f"Тип: {HOMEWORK_TASK_TYPE_LABELS.get(task_type, task_type)}",
        f"Задание: {task['prompt']}",
    ]
    if task_type == "translation":
        lines.append(f"Эталонный перевод: {_optional_task_value(task, 'expected_answer')}")
    elif task_type == "quiz":
        metadata = json.loads(task["metadata_json"]) if task["metadata_json"] else {}
        options = metadata.get("options", [])
        correct_index = metadata.get("correct_index")
        lines.append("Варианты:")
        for index, option in enumerate(options):
            mark = "✅" if index == correct_index else "•"
            lines.append(f"{mark} {option}")
    lines.append("")
    if answer is None:
        lines.append("Ответ ученика: пока нет ответа.")
    else:
        lines.append(f"Ответ ученика: {answer['answer']}")
        lines.append(f"Статус: {_answer_status_label(answer)}")
        if hasattr(answer, "keys") and "feedback" in answer.keys() and answer["feedback"]:
            lines.append(f"Комментарий: {answer['feedback']}")
    return "\n".join(lines)


def _homework_task_detail_keyboard(lesson_id: int, task_id: int, answer=None) -> InlineKeyboardMarkup:
    rows = []
    is_pending = answer is not None and hasattr(answer, "keys") and "is_correct" in answer.keys() and answer["is_correct"] is None
    if is_pending:
        rows.append([
            InlineKeyboardButton("✅ Верно", callback_data=f"{TEACHER_LESSON_HOMEWORK_REVIEW_CORRECT_PREFIX}{lesson_id}:{task_id}:{answer['id']}"),
            InlineKeyboardButton("❌ Неверно", callback_data=f"{TEACHER_LESSON_HOMEWORK_REVIEW_INCORRECT_PREFIX}{lesson_id}:{task_id}:{answer['id']}"),
        ])
    rows.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"{TEACHER_LESSON_HOMEWORK_DELETE_PREFIX}{lesson_id}:{task_id}")])
    rows.append([InlineKeyboardButton("⬅️ Домашнее задание", callback_data=f"{TEACHER_LESSON_HOMEWORK_PREFIX}{lesson_id}")])
    return InlineKeyboardMarkup(rows)


def _format_homework_delete_confirm(task) -> str:
    return "\n".join(["Удалить задание?", "", _homework_task_label(task)])


def _homework_delete_confirm_keyboard(lesson_id: int, task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"{TEACHER_LESSON_HOMEWORK_DELETE_CONFIRM_PREFIX}{lesson_id}:{task_id}")],
        [InlineKeyboardButton("↩️ Отмена", callback_data=f"{TEACHER_LESSON_HOMEWORK_OPEN_PREFIX}{lesson_id}:{task_id}")],
    ])


async def _show_lesson_homework(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, *, edit: bool = False) -> None:
    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)
    summary = service.get_lesson_summary(lesson_id)
    if summary is None:
        return
    tasks = service.list_homework_tasks(lesson_id)
    student = _assigned_student(db, service, lesson_id)
    answers = service.list_latest_homework_answers(lesson_id, int(student["id"])) if student is not None else {}
    text = _format_lesson_homework(summary, tasks, answers)
    markup = _lesson_homework_keyboard(lesson_id, tasks, answers)
    if edit and update.callback_query is not None:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def _show_lessons_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    lessons = _lesson_service(db).list_lessons()
    context.user_data.pop("teacher_action", None)
    if update.effective_message:
        await update.effective_message.reply_text(_format_lessons_screen(lessons), reply_markup=_lessons_list_keyboard(lessons))


async def _show_lesson_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    summary = _lesson_service(db).get_lesson_summary(lesson_id)
    if update.effective_message is None:
        return
    if summary is None:
        await update.effective_message.reply_text("Урок не найден.", reply_markup=_lessons_list_keyboard(_lesson_service(db).list_lessons()))
        return
    context.user_data["current_teacher_lesson_id"] = lesson_id
    assignment = _lesson_service(db).get_active_lesson_assignment(lesson_id)
    await update.effective_message.reply_text(_format_lesson_detail(summary, assignment), reply_markup=_lesson_detail_keyboard(lesson_id, assignment))



def _lesson_id_from_callback(data: str, prefix: str) -> int | None:
    lesson_id_text = data.removeprefix(prefix).strip()
    return int(lesson_id_text) if lesson_id_text.isdigit() else None


def _lesson_word_edit_from_callback(data: str) -> tuple[str, int, int] | None:
    payload = data.removeprefix(TEACHER_LESSON_WORD_EDIT_PREFIX).strip()
    field, sep1, rest = payload.partition(":")
    lesson_id_text, sep2, word_id_text = rest.partition(":")
    if field not in {"translation", "example", "topic"} or sep1 != ":" or sep2 != ":":
        return None
    if not lesson_id_text.isdigit() or not word_id_text.isdigit():
        return None
    return field, int(lesson_id_text), int(word_id_text)


def _lesson_word_ids_from_callback(data: str) -> tuple[int, int] | None:
    ids_text = data.removeprefix(TEACHER_LESSON_WORD_OPEN_PREFIX).strip()
    lesson_id_text, separator, word_id_text = ids_text.partition(":")
    if separator != ":" or not lesson_id_text.isdigit() or not word_id_text.isdigit():
        return None
    return int(lesson_id_text), int(word_id_text)


def _two_int_ids_from_callback(data: str, prefix: str) -> tuple[int, int] | None:
    ids_text = data.removeprefix(prefix).strip()
    lesson_id_text, separator, word_id_text = ids_text.partition(":")
    if separator != ":" or not lesson_id_text.isdigit() or not word_id_text.isdigit():
        return None
    return int(lesson_id_text), int(word_id_text)


def _three_int_ids_from_callback(data: str, prefix: str) -> tuple[int, int, int] | None:
    payload = data.removeprefix(prefix).strip()
    first_text, sep1, rest = payload.partition(":")
    second_text, sep2, third_text = rest.partition(":")
    if sep1 != ":" or sep2 != ":" or not first_text.isdigit() or not second_text.isdigit() or not third_text.isdigit():
        return None
    return int(first_text), int(second_text), int(third_text)


def _assigned_student(db: Database, service: LessonService, lesson_id: int):
    assignment = service.get_active_lesson_assignment(lesson_id)
    if assignment is None:
        return None
    return db.get_user_by_username(str(assignment["student_username"]))


async def handle_teacher_lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if not is_teacher(update, context):
        return
    data = query.data or ""
    db: Database = context.application.bot_data["db"]
    service = _lesson_service(db)
    if data == TEACHER_LESSONS_LIST_CALLBACK:
        lessons = service.list_lessons()
        if query.message is not None:
            await query.message.reply_text(_format_lessons_screen(lessons), reply_markup=_lessons_list_keyboard(lessons))
        return
    if data.startswith(TEACHER_LESSON_ASSIGN_STUDENT_PREFIX):
        parsed = _assign_student_ids_from_callback(data)
        if parsed is None:
            return
        lesson_id, username = parsed
        summary = service.get_lesson_summary(lesson_id)
        student = _student_by_label(_student_users(context), username)
        if summary is None:
            await query.edit_message_text("Урок не найден.")
            return
        if student is None:
            await query.edit_message_text("Ученик недоступен.", reply_markup=_assign_student_keyboard(lesson_id, _student_users(context)))
            return
        assignment = service.assign_lesson_to_student(lesson_id, str(student["username"]), _teacher_user_id(update, db))
        await NotificationService(db).notify_lesson_assigned(getattr(context, "bot", None), str(student["username"]), summary)
        await query.edit_message_text(_format_lesson_detail(summary, assignment), reply_markup=_lesson_detail_keyboard(lesson_id, assignment))
        return

    if data.startswith(TEACHER_LESSON_ASSIGN_PREFIX):
        lesson_id = _lesson_id_from_callback(data, TEACHER_LESSON_ASSIGN_PREFIX)
        summary = service.get_lesson_summary(lesson_id) if lesson_id is not None else None
        if lesson_id is None or summary is None:
            await query.edit_message_text("Урок не найден.")
            return
        students = _student_users(context)
        await query.edit_message_text(_format_assign_student_screen(summary, students), reply_markup=_assign_student_keyboard(lesson_id, students))
        return

    if data.startswith(TEACHER_LESSON_UNASSIGN_PREFIX):
        lesson_id = _lesson_id_from_callback(data, TEACHER_LESSON_UNASSIGN_PREFIX)
        summary = service.get_lesson_summary(lesson_id) if lesson_id is not None else None
        if lesson_id is None or summary is None:
            await query.edit_message_text("Урок не найден.")
            return
        service.unassign_lesson(lesson_id)
        await query.edit_message_text(_format_lesson_detail(summary, None), reply_markup=_lesson_detail_keyboard(lesson_id, None))
        return

    if data.startswith(TEACHER_LESSON_HOMEWORK_ADD_TYPE_PREFIX):
        payload = data.removeprefix(TEACHER_LESSON_HOMEWORK_ADD_TYPE_PREFIX)
        task_type, sep, lesson_id_text = payload.partition(":")
        if sep != ":" or task_type not in HOMEWORK_TASK_TYPE_LABELS or not lesson_id_text.isdigit():
            return
        lesson_id = int(lesson_id_text)
        summary = service.get_lesson_summary(lesson_id)
        if summary is None:
            await query.edit_message_text("Урок не найден.")
            return
        context.user_data["teacher_action"] = _CREATE_HOMEWORK_TASK
        context.user_data[_PENDING_HOMEWORK_TASK] = {"lesson_id": lesson_id, "task_type": task_type, "step": "prompt"}
        prompts = {
            "translation": "Введите слово или фразу для перевода:",
            "free": "Введите текст задания:",
            "quiz": "Введите вопрос:",
        }
        await query.edit_message_text(prompts[task_type])
        return

    if data.startswith(TEACHER_LESSON_HOMEWORK_ADD_PREFIX):
        lesson_id = _lesson_id_from_callback(data, TEACHER_LESSON_HOMEWORK_ADD_PREFIX)
        summary = service.get_lesson_summary(lesson_id) if lesson_id is not None else None
        if lesson_id is None or summary is None:
            await query.edit_message_text("Урок не найден.")
            return
        await query.edit_message_text("Выберите тип задания:", reply_markup=_homework_type_picker_keyboard(lesson_id))
        return

    if data.startswith(TEACHER_LESSON_HOMEWORK_CANCEL_PREFIX):
        lesson_id = _lesson_id_from_callback(data, TEACHER_LESSON_HOMEWORK_CANCEL_PREFIX)
        if lesson_id is None or service.get_lesson_summary(lesson_id) is None:
            await query.edit_message_text("Урок не найден.")
            return
        context.user_data.pop("teacher_action", None)
        context.user_data.pop(_PENDING_HOMEWORK_TASK, None)
        await _show_lesson_homework(update, context, lesson_id, edit=True)
        return

    if data.startswith(TEACHER_LESSON_HOMEWORK_DELETE_CONFIRM_PREFIX):
        ids = _two_int_ids_from_callback(data, TEACHER_LESSON_HOMEWORK_DELETE_CONFIRM_PREFIX)
        if ids is None:
            return
        lesson_id, task_id = ids
        if service.get_lesson_summary(lesson_id) is None:
            await query.edit_message_text("Урок не найден.")
            return
        service.delete_homework_task(lesson_id, task_id)
        await _show_lesson_homework(update, context, lesson_id, edit=True)
        return

    if data.startswith(TEACHER_LESSON_HOMEWORK_DELETE_PREFIX):
        ids = _two_int_ids_from_callback(data, TEACHER_LESSON_HOMEWORK_DELETE_PREFIX)
        if ids is None:
            return
        lesson_id, task_id = ids
        summary = service.get_lesson_summary(lesson_id)
        task = service.get_homework_task(lesson_id, task_id) if summary is not None else None
        if summary is None or task is None:
            await query.edit_message_text("Задание не найдено.")
            return
        await query.edit_message_text(_format_homework_delete_confirm(task), reply_markup=_homework_delete_confirm_keyboard(lesson_id, task_id))
        return

    for review_prefix, is_correct in ((TEACHER_LESSON_HOMEWORK_REVIEW_CORRECT_PREFIX, True), (TEACHER_LESSON_HOMEWORK_REVIEW_INCORRECT_PREFIX, False)):
        if not data.startswith(review_prefix):
            continue
        ids = _three_int_ids_from_callback(data, review_prefix)
        if ids is None:
            return
        lesson_id, task_id, answer_id = ids
        summary = service.get_lesson_summary(lesson_id)
        task = service.get_homework_task(lesson_id, task_id) if summary is not None else None
        answer = service.repository.get_homework_answer(task_id, answer_id) if task is not None else None
        if summary is None or task is None or answer is None:
            await query.edit_message_text("Ответ не найден.")
            return
        context.user_data["teacher_action"] = _REVIEW_HOMEWORK_ANSWER
        context.user_data[_PENDING_HOMEWORK_REVIEW] = {"lesson_id": lesson_id, "task_id": task_id, "answer_id": answer_id, "is_correct": is_correct}
        await query.edit_message_text("Добавить комментарий ученику? Напишите текст, или отправьте '-' чтобы пропустить.")
        return

    if data.startswith(TEACHER_LESSON_HOMEWORK_OPEN_PREFIX):
        ids = _two_int_ids_from_callback(data, TEACHER_LESSON_HOMEWORK_OPEN_PREFIX)
        if ids is None:
            return
        lesson_id, task_id = ids
        summary = service.get_lesson_summary(lesson_id)
        task = service.get_homework_task(lesson_id, task_id) if summary is not None else None
        if summary is None or task is None:
            await query.edit_message_text("Задание не найдено.")
            return
        student = _assigned_student(db, service, lesson_id)
        answer = service.get_latest_homework_answer(task_id, int(student["id"])) if student is not None else None
        await query.edit_message_text(_format_homework_task_detail(summary, task, answer), reply_markup=_homework_task_detail_keyboard(lesson_id, task_id, answer))
        return

    if data.startswith(TEACHER_LESSON_WORDS_AI_EDIT_PREFIX):
        ids = _ai_translation_edit_ids_from_callback(data)
        if ids is None:
            return
        lesson_id, word_id = ids
        if service.get_lesson_summary(lesson_id) is None:
            await query.edit_message_text("Черновик не найден.", reply_markup=_ai_translation_fallback_keyboard(lesson_id))
            return
        translations = _ai_translation_draft_for_lesson(context, lesson_id)
        if not translations:
            _clear_ai_translation_state(context)
            await query.edit_message_text("Черновик не найден.", reply_markup=_ai_translation_fallback_keyboard(lesson_id))
            return
        item = _find_ai_translation_draft_item(translations, word_id)
        if item is None:
            await query.edit_message_text("Пункт черновика не найден.", reply_markup=_ai_translation_missing_item_keyboard(lesson_id))
            return
        if service.get_lesson_word(lesson_id, word_id) is None:
            _clear_ai_translation_state(context)
            await query.edit_message_text("Черновик не найден.", reply_markup=_ai_translation_fallback_keyboard(lesson_id))
            return
        context.user_data["teacher_action"] = _EDIT_AI_TRANSLATION_DRAFT
        context.user_data[_PENDING_AI_TRANSLATION_EDIT] = {"lesson_id": lesson_id, "word_id": word_id}
        await query.edit_message_text(
            "\n".join([
                "Введите новый перевод для:",
                "",
                str(item["english"]),
                "",
                "Текущий перевод:",
                str(item.get("translation") or ""),
                "",
                "Чтобы очистить значение, отправьте:",
                "-",
            ])
        )
        return

    if data.startswith(TEACHER_LESSON_WORD_EDIT_PREFIX):
        parsed = _lesson_word_edit_from_callback(data)
        if parsed is None:
            return
        field, lesson_id, word_id = parsed
        if service.get_lesson_word(lesson_id, word_id) is None:
            await query.edit_message_text("Слово не найдено.")
            return
        context.user_data["teacher_action"] = _EDIT_LESSON_WORD
        context.user_data[_PENDING_WORD_EDIT] = {"field": field, "lesson_id": lesson_id, "word_id": word_id}
        prompts = {
            "translation": "Введите перевод слова.",
            "example": "Введите пример для слова.",
            "topic": "Введите тему для слова.",
        }
        await query.edit_message_text(f"{prompts[field]}\n\nЧтобы очистить поле, отправьте '-' или '—' или 'пусто'.")
        return

    for ai_prefix in (TEACHER_LESSON_WORDS_AI_TRANSLATE_PREFIX, TEACHER_LESSON_WORDS_AI_APPLY_PREFIX, TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX, TEACHER_LESSON_WORDS_AI_PREVIEW_PREFIX):
        if not data.startswith(ai_prefix):
            continue
        lesson_id = _lesson_id_from_callback(data, ai_prefix)
        if lesson_id is None or service.get_lesson_summary(lesson_id) is None:
            if query.message is not None:
                await query.message.reply_text("Урок не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        context.user_data["current_teacher_lesson_id"] = lesson_id
        if ai_prefix == TEACHER_LESSON_WORDS_AI_CANCEL_PREFIX:
            _clear_ai_translation_state(context)
            await _show_lesson_words_selection(update, context, lesson_id)
            return
        if ai_prefix == TEACHER_LESSON_WORDS_AI_PREVIEW_PREFIX:
            translations = _ai_translation_draft_for_lesson(context, lesson_id)
            if not translations:
                _clear_ai_translation_state(context)
                await query.edit_message_text("Черновик не найден.", reply_markup=_ai_translation_fallback_keyboard(lesson_id))
                return
            await query.edit_message_text(_format_ai_translation_preview(translations), reply_markup=_ai_translation_preview_keyboard(lesson_id, translations))
            return
        if ai_prefix == TEACHER_LESSON_WORDS_AI_APPLY_PREFIX:
            translations = _ai_translation_draft_for_lesson(context, lesson_id)
            if not translations:
                _clear_ai_translation_state(context)
                await _show_lesson_words_selection(update, context, lesson_id)
                return
            for item in translations:
                db.update_word_translation(lesson_id, int(item["word_id"]), item.get("translation") or "")
            _clear_ai_translation_state(context)
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        selected_rows = _selected_word_rows(service, context, lesson_id)
        if not selected_rows:
            await query.edit_message_text("Выберите хотя бы одно слово.", reply_markup=_lesson_words_selection_keyboard(lesson_id, service.list_lesson_words(lesson_id), set()))
            return
        await query.edit_message_text("Генерирую переводы...")
        english_words = [str(word["english"]) for word in selected_rows]
        ai_translations = await generate_word_translations(english_words)
        if ai_translations is None:
            await query.edit_message_text("Не удалось получить перевод.\n\nПопробуйте ещё раз.", reply_markup=_lesson_words_selection_keyboard(lesson_id, service.list_lesson_words(lesson_id), _selected_lesson_words(context, lesson_id)))
            return
        by_english = {item["english"].casefold(): item["translation"] for item in ai_translations}
        draft_translations = [
            {"word_id": int(word["id"]), "english": str(word["english"]), "translation": by_english[str(word["english"]).casefold()]}
            for word in selected_rows
        ]
        context.user_data[_PENDING_AI_TRANSLATION] = {"lesson_id": lesson_id, "translations": draft_translations}
        await query.edit_message_text(_format_ai_translation_preview(draft_translations), reply_markup=_ai_translation_preview_keyboard(lesson_id, draft_translations))
        return
    if data.startswith(TEACHER_LESSON_WORD_OPEN_PREFIX):
        ids = _lesson_word_ids_from_callback(data)
        if ids is None:
            return
        lesson_id, word_id = ids
        summary = service.get_lesson_summary(lesson_id)
        word = service.get_lesson_word(lesson_id, word_id) if summary is not None else None
        context.user_data["current_teacher_lesson_id"] = lesson_id
        await query.edit_message_text(_format_lesson_word_detail(summary, word), reply_markup=_lesson_word_detail_keyboard(lesson_id, word_id))
        return
    if data.startswith(TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX):
        ids = _two_int_ids_from_callback(data, TEACHER_LESSON_WORDS_SELECT_TOGGLE_PREFIX)
        if ids is None:
            return
        lesson_id, word_id = ids
        if service.get_lesson_summary(lesson_id) is None:
            if query.message is not None:
                await query.message.reply_text("Урок не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        words = service.list_lesson_words(lesson_id)
        actual_ids = _actual_word_ids(words)
        selected = _prune_lesson_words_selection(context, lesson_id, words)
        if word_id in actual_ids:
            if word_id in selected:
                selected.remove(word_id)
            else:
                selected.add(word_id)
        context.user_data["current_teacher_lesson_id"] = lesson_id
        await _show_lesson_words_selection(update, context, lesson_id)
        return
    for select_prefix in (
        TEACHER_LESSON_WORDS_SELECT_ALL_PREFIX,
        TEACHER_LESSON_WORDS_SELECT_CLEAR_PREFIX,
        TEACHER_LESSON_WORDS_SELECT_DONE_PREFIX,
        TEACHER_LESSON_WORDS_SELECT_PREFIX,
    ):
        if not data.startswith(select_prefix):
            continue
        lesson_id = _lesson_id_from_callback(data, select_prefix)
        if lesson_id is None or service.get_lesson_summary(lesson_id) is None:
            if query.message is not None:
                await query.message.reply_text("Урок не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        context.user_data["current_teacher_lesson_id"] = lesson_id
        if select_prefix == TEACHER_LESSON_WORDS_SELECT_DONE_PREFIX:
            selections = context.user_data.get(_SELECTED_LESSON_WORDS, {})
            selections.pop(lesson_id, None)
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        words = service.list_lesson_words(lesson_id)
        selected = _prune_lesson_words_selection(context, lesson_id, words)
        if not words and select_prefix == TEACHER_LESSON_WORDS_SELECT_PREFIX:
            await query.edit_message_text("В этом уроке пока нет слов.", reply_markup=_lesson_words_keyboard(lesson_id, words))
            return
        if select_prefix == TEACHER_LESSON_WORDS_SELECT_ALL_PREFIX:
            selected.clear()
            selected.update(_actual_word_ids(words))
        elif select_prefix == TEACHER_LESSON_WORDS_SELECT_CLEAR_PREFIX:
            selected.clear()
        await _show_lesson_words_selection(update, context, lesson_id)
        return
    for words_prefix in (TEACHER_LESSON_WORDS_ADD_PREFIX, TEACHER_LESSON_WORDS_CONFIRM_PREFIX, TEACHER_LESSON_WORDS_CANCEL_PREFIX):
        if not data.startswith(words_prefix):
            continue
        lesson_id = _lesson_id_from_callback(data, words_prefix)
        if lesson_id is None or service.get_lesson_summary(lesson_id) is None:
            if query.message is not None:
                await query.message.reply_text("Урок не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        context.user_data["current_teacher_lesson_id"] = lesson_id
        if words_prefix == TEACHER_LESSON_WORDS_ADD_PREFIX:
            context.user_data["teacher_action"] = _IMPORT_LESSON_WORDS
            context.user_data[_PENDING_LESSON_WORDS] = {"lesson_id": lesson_id, "source": "manual", "words": []}
            if query.message is not None:
                await query.message.reply_text(_lesson_words_prompt())
            return
        draft = context.user_data.get(_PENDING_LESSON_WORDS)
        if words_prefix == TEACHER_LESSON_WORDS_CANCEL_PREFIX:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_LESSON_WORDS, None)
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        if not draft or int(draft.get("lesson_id", 0)) != lesson_id or not draft.get("words"):
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        service.add_lesson_words(lesson_id, list(draft["words"]), owner_user_id=_teacher_user_id(update, db))
        context.user_data.pop("teacher_action", None)
        context.user_data.pop(_PENDING_LESSON_WORDS, None)
        await _show_lesson_words(update, context, lesson_id, edit=True)
        return
    for prefix in TEACHER_LESSON_CALLBACK_PREFIXES:
        if not data.startswith(prefix):
            continue
        lesson_id = _lesson_id_from_callback(data, prefix)
        if lesson_id is None:
            return
        summary = service.get_lesson_summary(lesson_id)
        if summary is None:
            if query.message is not None:
                await query.message.reply_text("Урок не найден.", reply_markup=_lessons_list_keyboard(service.list_lessons()))
            return
        context.user_data["current_teacher_lesson_id"] = lesson_id
        if prefix == TEACHER_LESSON_BACK_PREFIX:
            await query.edit_message_text(_format_lesson_detail(summary, service.get_active_lesson_assignment(lesson_id)), reply_markup=_lesson_detail_keyboard(lesson_id, service.get_active_lesson_assignment(lesson_id)))
            return
        section_by_prefix = {
            TEACHER_LESSON_WORDS_PREFIX: "words",
            TEACHER_LESSON_GRAMMAR_PREFIX: "grammar",
            TEACHER_LESSON_EXERCISES_PREFIX: "exercises",
            TEACHER_LESSON_HOMEWORK_PREFIX: "homework",
            TEACHER_LESSON_AI_PREFIX: "ai",
        }
        if prefix == TEACHER_LESSON_WORDS_PREFIX:
            await _show_lesson_words(update, context, lesson_id, edit=True)
            return
        if prefix == TEACHER_LESSON_HOMEWORK_PREFIX:
            await _show_lesson_homework(update, context, lesson_id, edit=True)
            return
        await query.edit_message_text(_format_lesson_section(summary, section_by_prefix[prefix]), reply_markup=_lesson_section_keyboard(lesson_id))
        return

def _resolver(context: ContextTypes.DEFAULT_TYPE) -> RoleResolver:
    settings: Settings = context.application.bot_data["settings"]
    return RoleResolver(settings, context.application.bot_data.get("db"))


def is_teacher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    role = _resolver(context).role_for(user.username)
    return role is Role.TEACHER or (role is Role.ADMIN and bool(context.user_data.get("admin_teacher_view")))


def _student_users(context: ContextTypes.DEFAULT_TYPE) -> list:
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    resolver = _resolver(context)
    student_usernames = set(resolver.student_usernames) | {"wp_bvv"}
    return db.list_student_targets(student_usernames, getattr(settings, "display_names", {}))


def _student_keyboard(students: list, back_label: str = "↩️ Меню учителя") -> ReplyKeyboardMarkup:
    rows = []
    for student in students:
        suffix = " — ещё не запускал бота" if not student.get("has_user", True) else ""
        rows.append([KeyboardButton(f"{student['display_name']} (@{student['username']}){suffix}")])
    rows.append([KeyboardButton(back_label)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _is_student_target_available(context: ContextTypes.DEFAULT_TYPE, username: str) -> bool:
    return _student_by_label(_student_users(context), username) is not None

def _student_by_label(students: list, text: str):
    normalized_text = text.casefold()
    for student in students:
        labels = {
            f"{student['display_name']} (@{student['username']})".casefold(),
            f"{student['display_name']} (@{student['username']}) — ещё не запускал бота".casefold(),
            f"@{student['username']}".casefold(),
            str(student["display_name"]).casefold(),
            str(student["username"]).casefold(),
        }
        if normalized_text in labels:
            return student
    return None


def _optional_value(text: str) -> str | None:
    value = text.strip()
    return None if value.casefold() in _OPTIONAL_SKIP else value


def _teacher_user_id(update: Update, db: Database) -> int | None:
    tg_user = update.effective_user
    if tg_user is None:
        return None
    user = db.get_user_by_telegram_id(tg_user.id)
    return int(user["id"]) if user is not None else None


def _format_created_lesson(lesson, student) -> str:
    return "\n".join(
        [
            "Урок создан",
            f"Название: {lesson['title']}",
            f"Ученик: {student['display_name']} (@{student['username']})",
            f"Тема: {lesson['theme'] or '-'}",
            f"Грамматика: {lesson['grammar_topic'] or '-'}",
            f"Статус: {_status_label(lesson['status'])}",
        ]
    )


def _format_teacher_lessons(lessons: list) -> str:
    if not lessons:
        return "Пока нет уроков."
    lines = ["📋 Мои уроки:"]
    for lesson in lessons:
        student = f"{lesson['student_display_name']} (@{lesson['student_username']})"
        lines.append(f"• {lesson['title']} — {student} — тема: {lesson['theme'] or '-'} — статус: {_status_label(lesson['status'])}")
    return "\n".join(lines)

def _format_students(students: list) -> str:
    if not students:
        return "Пока нет учеников: student users из allowed users ещё не заходили в бот."
    lines = ["👤 Ученики:"]
    for student in students:
        suffix = " — ещё не запускал бота" if not student.get("has_user", True) else ""
        lines.append(f"• {student['display_name']} (@{student['username']}){suffix}")
    return "\n".join(lines)


def _format_student_progress(db: Database, student) -> str:
    if not student.get("has_user", True) or student.get("id") is None:
        return NOT_STARTED_TEXT
    activity = db.get_daily_activity(student["id"], _today_moscow())
    weak_words = db.list_weak_words(student["id"], limit=10)
    weak_lines = [f"{i}. {word['english']} — {word['translation']} (score: {word['progress_score'] or 0}, forgot: {word['times_forgotten'] or 0})" for i, word in enumerate(weak_words, start=1)]
    if not weak_lines:
        weak_lines = ["пока нет слабых слов"]
    parts = [
        f"📊 Прогресс: {student['display_name']} (@{student['username']})",
        f"• всего слов: {db.count_words(student['id'])}",
        f"• карточек сегодня: {activity['cards_reviewed'] if activity else 0}",
        f"• XP сегодня: {activity['xp_earned'] if activity else 0}",
        f"• streak: {activity['streak_days'] if activity else 0}",
        "",
        "Top-10 слабых слов:",
        *weak_lines,
    ]
    return "\n".join(parts)


async def show_teacher_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("teacher_action", None)
    if update.effective_message:
        await update.effective_message.reply_text("Меню учителя:", reply_markup=teacher_menu_keyboard())


async def handle_teacher_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_message is None or not is_teacher(update, context):
        return False
    text = update.effective_message.text or ""
    db: Database = context.application.bot_data["db"]

    if text == EXIT_STUDENT_MODE:
        context.user_data.pop("impersonated_user_id", None)
        context.user_data.pop("teacher_action", None)
        await update.effective_message.reply_text("Вы вышли из режима ученика.", reply_markup=teacher_menu_keyboard())
        return True

    if context.user_data.get("impersonated_user_id"):
        return False

    if text in {"↩️ Меню учителя", "↩️ Teacher menu", TEACHER_LESSONS_BACK, "/start"}:
        await show_teacher_menu(update, context)
        return True
    if text == TEACHER_STUDENTS:
        await update.effective_message.reply_text(_format_students(_student_users(context)), reply_markup=teacher_menu_keyboard())
        return True
    if text == ADD_STUDENT:
        context.user_data["teacher_action"] = _ADD_STUDENT
        await update.effective_message.reply_text("Введите username ученика, например @privetnormalno")
        return True
    if text in {TEACHER_LESSONS, LESSON_BACK_TO_LIST}:
        await _show_lessons_screen(update, context)
        return True
    if text == TEACHER_CREATE_LESSON:
        context.user_data["teacher_action"] = _CREATE_LESSON_TITLE
        context.user_data.pop("lesson_draft", None)
        await update.effective_message.reply_text("Введите название урока.\n\nНапример:\nLesson 15 — Food")
        return True
    if text == TEACHER_MY_LESSONS:
        teacher_id = _teacher_user_id(update, db)
        lessons = db.list_lessons_for_teacher(teacher_id, limit=10) if teacher_id is not None else []
        await update.effective_message.reply_text(_format_teacher_lessons(lessons), reply_markup=teacher_lessons_keyboard())
        return True
    if text.startswith(TEACHER_LESSON_OPEN_PREFIX):
        lesson_id_text = text.removeprefix(TEACHER_LESSON_OPEN_PREFIX).strip()
        if lesson_id_text.isdigit():
            await _show_lesson_detail(update, context, int(lesson_id_text))
            return True

    if text in {TEACHER_PROGRESS, TEACHER_IMPERSONATE}:
        students = _student_users(context)
        if not students:
            await update.effective_message.reply_text("Пока нет учеников для выбора.", reply_markup=teacher_menu_keyboard())
            return True
        context.user_data["teacher_action"] = _SELECT_PROGRESS if text == TEACHER_PROGRESS else _SELECT_IMPERSONATE
        await update.effective_message.reply_text("Выберите ученика:", reply_markup=_student_keyboard(students))
        return True

    action = context.user_data.get("teacher_action")
    if action == _EDIT_AI_TRANSLATION_DRAFT:
        edit = context.user_data.get(_PENDING_AI_TRANSLATION_EDIT) or {}
        lesson_id = int(edit.get("lesson_id") or 0)
        word_id = int(edit.get("word_id") or 0)
        translations = _ai_translation_draft_for_lesson(context, lesson_id) if lesson_id else None
        if not translations:
            _clear_ai_translation_state(context)
            await update.effective_message.reply_text("Черновик не найден.", reply_markup=_ai_translation_fallback_keyboard(lesson_id))
            return True
        item = _find_ai_translation_draft_item(translations, word_id) if word_id else None
        if item is None:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_AI_TRANSLATION_EDIT, None)
            await update.effective_message.reply_text("Пункт черновика не найден.", reply_markup=_ai_translation_missing_item_keyboard(lesson_id))
            return True
        value = text.strip()
        if not value:
            await update.effective_message.reply_text("Перевод не может быть пустым. Отправьте '-' или '—', чтобы очистить значение.")
            return True
        if len(value) > 500:
            await update.effective_message.reply_text("Максимум 500 символов.")
            return True
        item["translation"] = "" if value in {"-", "—"} else value
        context.user_data.pop("teacher_action", None)
        context.user_data.pop(_PENDING_AI_TRANSLATION_EDIT, None)
        await update.effective_message.reply_text(_format_ai_translation_preview(translations), reply_markup=_ai_translation_preview_keyboard(lesson_id, translations))
        return True
    if action == _EDIT_LESSON_WORD:
        draft = context.user_data.get(_PENDING_WORD_EDIT) or {}
        field = str(draft.get("field") or "")
        lesson_id = int(draft.get("lesson_id") or 0)
        word_id = int(draft.get("word_id") or 0)
        if field not in {"translation", "example", "topic"} or not lesson_id or not word_id:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_WORD_EDIT, None)
            return False
        try:
            value = _normalize_word_edit_value(text, _word_edit_limit(field))
        except ValueError as error:
            await update.effective_message.reply_text(str(error))
            return True
        if value is None and field == "translation":
            value = ""
        saved = _update_word_field(db, lesson_id, word_id, field, value)
        context.user_data.pop("teacher_action", None)
        context.user_data.pop(_PENDING_WORD_EDIT, None)
        if not saved:
            await update.effective_message.reply_text("Слово не найдено.")
            return True
        summary = _lesson_service(db).get_lesson_summary(lesson_id)
        word = _lesson_service(db).get_lesson_word(lesson_id, word_id)
        await update.effective_message.reply_text(_format_lesson_word_detail(summary, word), reply_markup=_lesson_word_detail_keyboard(lesson_id, word_id))
        return True
    if action == _CREATE_HOMEWORK_TASK:
        draft = context.user_data.get(_PENDING_HOMEWORK_TASK) or {}
        lesson_id = int(draft.get("lesson_id") or 0)
        task_type = str(draft.get("task_type") or "")
        step = str(draft.get("step") or "")
        service = _lesson_service(db)
        if not lesson_id or task_type not in HOMEWORK_TASK_TYPE_LABELS or service.get_lesson_summary(lesson_id) is None:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_HOMEWORK_TASK, None)
            return False

        async def _finish(task_creator) -> bool:
            try:
                task = task_creator()
            except HomeworkTaskError as error:
                await update.effective_message.reply_text(str(error))
                return True
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_HOMEWORK_TASK, None)
            await update.effective_message.reply_text("Задание добавлено ✅")
            assignment = service.get_active_lesson_assignment(lesson_id)
            if assignment is not None:
                lesson_summary = service.get_lesson_summary(lesson_id)
                await NotificationService(db).notify_homework_assigned(
                    getattr(context, "bot", None), str(assignment["student_username"]), lesson_summary, task
                )
            await _show_lesson_homework(update, context, lesson_id)
            return True

        if task_type == "translation":
            if step == "prompt":
                if not text.strip():
                    await update.effective_message.reply_text("Задание не может быть пустым. Введите слово или фразу для перевода:")
                    return True
                draft["prompt"] = text.strip()
                draft["step"] = "answer"
                await update.effective_message.reply_text("Введите эталонный перевод, или '-' чтобы бот проверял только через AI:")
                return True
            expected = None if text.strip() in {"-", "—"} else text
            return await _finish(lambda: service.add_translation_task(lesson_id, draft.get("prompt", ""), expected))

        if task_type == "free":
            return await _finish(lambda: service.add_free_task(lesson_id, text))

        if task_type == "quiz":
            if step == "prompt":
                if not text.strip():
                    await update.effective_message.reply_text("Вопрос не может быть пустым. Введите вопрос:")
                    return True
                draft["prompt"] = text.strip()
                draft["step"] = "options"
                await update.effective_message.reply_text("Введите варианты ответа, каждый с новой строки (минимум 2, максимум 6):")
                return True
            if step == "options":
                options = [line.strip() for line in text.splitlines() if line.strip()]
                if len(options) < 2:
                    await update.effective_message.reply_text("Нужно минимум 2 варианта, каждый с новой строки. Попробуйте ещё раз:")
                    return True
                if len(options) > 6:
                    await update.effective_message.reply_text("Слишком много вариантов: максимум 6. Попробуйте ещё раз:")
                    return True
                draft["options"] = options
                draft["step"] = "correct"
                option_lines = "\n".join(f"{index}. {option}" for index, option in enumerate(options, start=1))
                await update.effective_message.reply_text(f"Варианты:\n{option_lines}\n\nВведите номер правильного варианта:")
                return True
            options = list(draft.get("options") or [])
            if not text.strip().isdigit():
                await update.effective_message.reply_text("Введите число.")
                return True
            choice = int(text.strip())
            if not (1 <= choice <= len(options)):
                await update.effective_message.reply_text(f"Введите число от 1 до {len(options)}.")
                return True
            return await _finish(lambda: service.add_quiz_task(lesson_id, draft.get("prompt", ""), options, choice - 1))
        return False

    if action == _REVIEW_HOMEWORK_ANSWER:
        draft = context.user_data.get(_PENDING_HOMEWORK_REVIEW) or {}
        lesson_id = int(draft.get("lesson_id") or 0)
        task_id = int(draft.get("task_id") or 0)
        answer_id = int(draft.get("answer_id") or 0)
        is_correct = bool(draft.get("is_correct"))
        service = _lesson_service(db)
        if not lesson_id or not task_id or not answer_id:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_HOMEWORK_REVIEW, None)
            return False
        feedback = None if text.strip() in {"-", "—"} else text
        try:
            service.review_homework_answer(lesson_id, task_id, answer_id, is_correct, feedback)
        except HomeworkTaskError as error:
            await update.effective_message.reply_text(str(error))
            return True
        except ValueError:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_HOMEWORK_REVIEW, None)
            await update.effective_message.reply_text("Ответ не найден.")
            return True
        context.user_data.pop("teacher_action", None)
        context.user_data.pop(_PENDING_HOMEWORK_REVIEW, None)
        summary = service.get_lesson_summary(lesson_id)
        task = service.get_homework_task(lesson_id, task_id)
        answer = service.repository.get_homework_answer(task_id, answer_id)
        await update.effective_message.reply_text(
            _format_homework_task_detail(summary, task, answer), reply_markup=_homework_task_detail_keyboard(lesson_id, task_id, answer)
        )
        return True

    if action == _IMPORT_LESSON_WORDS:
        draft = context.user_data.get(_PENDING_LESSON_WORDS) or {}
        lesson_id = int(draft.get("lesson_id") or context.user_data.get("current_teacher_lesson_id") or 0)
        if not lesson_id:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop(_PENDING_LESSON_WORDS, None)
            return False
        try:
            words = normalize_lesson_words_import(text)
        except LessonWordImportError as error:
            await update.effective_message.reply_text(str(error))
            return True
        context.user_data[_PENDING_LESSON_WORDS] = {"lesson_id": lesson_id, "source": "manual", "words": words}
        await update.effective_message.reply_text(_format_lesson_words_preview(words), reply_markup=_lesson_words_preview_keyboard(lesson_id))
        return True
    if action == _ADD_STUDENT:
        service = StudentAccessService(db)
        username = service.normalize_username(text)
        if not service.validate_username(username):
            await update.effective_message.reply_text("Не похоже на Telegram username.\n\nВведите username в формате @username.")
            return True
        result = service.add_student_access(username, added_by_user_id=_teacher_user_id(update, db))
        context.user_data.pop("teacher_action", None)
        if result.status == "already_active":
            reply = f"Ученик @{result.username} уже добавлен."
        elif result.status == "reactivated":
            reply = f"Доступ для @{result.username} снова включён ✅"
        else:
            reply = (
                f"Ученик @{result.username} добавлен ✅\n\n"
                "Если он ещё не запускал бота, попросите его открыть бота и нажать /start."
            )
        await update.effective_message.reply_text(reply, reply_markup=teacher_menu_keyboard())
        return True
    if action == _CREATE_LESSON_STUDENT:
        student = _student_by_label(_student_users(context), text)
        if student is None:
            await update.effective_message.reply_text("Не нашёл такого ученика. Выберите ученика из списка.")
            return True
        if not student.get("has_user", True) or student.get("id") is None:
            await update.effective_message.reply_text(NOT_STARTED_TEXT)
            return True
        context.user_data["lesson_draft"] = {"student_user_id": student["id"]}
        context.user_data["teacher_action"] = _CREATE_LESSON_TITLE
        await update.effective_message.reply_text("Введите название урока:")
        return True
    if action == _CREATE_LESSON_TITLE:
        title = text.strip()
        if not title:
            await update.effective_message.reply_text("Название урока не может быть пустым. Введите название урока:")
            return True
        lesson = _lesson_service(db).create_lesson(title, created_by_user_id=_teacher_user_id(update, db))
        context.user_data.pop("teacher_action", None)
        context.user_data.pop("lesson_draft", None)
        await _show_lesson_detail(update, context, int(lesson["id"]))
        return True
    if action == _CREATE_LESSON_THEME:
        context.user_data.setdefault("lesson_draft", {})["theme"] = _optional_value(text)
        context.user_data["teacher_action"] = _CREATE_LESSON_GRAMMAR
        await update.effective_message.reply_text("Введите грамматическую тему или '-' чтобы пропустить:")
        return True
    if action == _CREATE_LESSON_GRAMMAR:
        draft = context.user_data.get("lesson_draft", {})
        student = db.get_user_by_id(int(draft["student_user_id"]))
        if student is None:
            context.user_data.pop("teacher_action", None)
            context.user_data.pop("lesson_draft", None)
            await update.effective_message.reply_text("Не нашёл выбранного ученика.", reply_markup=teacher_lessons_keyboard())
            return True
        teacher_id = _teacher_user_id(update, db)
        lesson = db.create_lesson(int(draft["student_user_id"]), teacher_id, draft["title"], draft.get("theme"), _optional_value(text))
        context.user_data.pop("teacher_action", None)
        context.user_data.pop("lesson_draft", None)
        await update.effective_message.reply_text(_format_created_lesson(lesson, student), reply_markup=teacher_lessons_keyboard())
        return True
    if action in {_SELECT_PROGRESS, _SELECT_IMPERSONATE}:
        student = _student_by_label(_student_users(context), text)
        if student is None:
            await update.effective_message.reply_text("Не нашёл такого ученика. Выберите ученика из списка.")
            return True
        context.user_data.pop("teacher_action", None)
        if action == _SELECT_PROGRESS:
            await update.effective_message.reply_text(_format_student_progress(db, student), reply_markup=teacher_menu_keyboard())
            return True
        if not student.get("has_user", True) or student.get("id") is None:
            await update.effective_message.reply_text(NOT_STARTED_TEXT, reply_markup=teacher_menu_keyboard())
            return True
        context.user_data["impersonated_user_id"] = student["id"]
        context.user_data.pop("training", None)
        await update.effective_message.reply_text(
            f"👀 Режим ученика: {student['display_name']}. Действия выполняются как выбранный ученик.",
            reply_markup=main_menu_keyboard(include_exit_student_mode=True),
        )
        return True

    return False
