from telegram import KeyboardButton, ReplyKeyboardMarkup

ADD_WORD = "➕ Добавить слово"
BULK_ADD_WORDS = "📥 Добавить список слов"
MY_WORDS = "📚 Мой словарь"
WORD_EXCHANGE = "🔄 Обмен словами"
MY_CARDS = "🎯 Мои карточки"
GAME_SESSION = "🎮 Игра на 10 слов"
MY_MISTAKES = "😵 Мои ошибки"
PROGRESS = "📊 Прогресс"
SHOW_TRANSLATION = "👀 Показать ответ"
REMEMBER = "✅ Помню"
FORGET = "❌ Не помню"
KNOW = "✅ Знаю"
DONT_KNOW = "❌ Не знаю"
SKIP = "⏭ Пропустить"
NEXT_CARD = "➡️ Следующая карточка"
STOP = "🛑 Закончить"
MISTAKE = "😬 Ошибся"
I_WAS_RIGHT = "😬 Я был прав"
TEACHER_STUDENTS = "👤 Ученики"
TEACHER_PROGRESS = "📊 Прогресс ученика"
TEACHER_IMPERSONATE = "👀 Режим ученика"
TEACHER_LESSONS = "📚 Уроки"
ADD_STUDENT = "➕ Добавить ученика"
TEACHER_CREATE_LESSON = "➕ Создать урок"
TEACHER_MY_LESSONS = "📋 Мои уроки"
EXIT_STUDENT_MODE = "↩️ Выйти из режима ученика"
ADMIN_MENU = "🛠 Админ"
ADMIN_STUDENT_VIEW = "👨‍🎓 Войти как ученик"
ADMIN_TEACHER_VIEW = "👩‍🏫 Войти как учитель"
ADMIN_USERS = "📊 Все пользователи"
ADMIN_MY_MENU = "↩️ Моё меню"

# Backward-compatible aliases for old imports / older Telegram keyboards.
ALL_WORDS = WORD_EXCHANGE
ALL_CARDS = WORD_EXCHANGE


def main_menu_keyboard(include_exit_student_mode: bool = False, include_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(ADD_WORD), KeyboardButton(BULK_ADD_WORDS)],
        [KeyboardButton(MY_WORDS), KeyboardButton(WORD_EXCHANGE)],
        [KeyboardButton(MY_CARDS), KeyboardButton(GAME_SESSION)],
        [KeyboardButton(MY_MISTAKES), KeyboardButton(PROGRESS)],
    ]
    if include_admin:
        rows.append([KeyboardButton(ADMIN_MENU)])
    if include_exit_student_mode:
        rows.append([KeyboardButton(EXIT_STUDENT_MODE)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ADMIN_STUDENT_VIEW)],
            [KeyboardButton(ADMIN_TEACHER_VIEW)],
            [KeyboardButton(ADMIN_USERS)],
            [KeyboardButton(ADD_STUDENT)],
            [KeyboardButton(ADMIN_MY_MENU)],
        ],
        resize_keyboard=True,
    )


def teacher_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(TEACHER_STUDENTS)],
            [KeyboardButton(TEACHER_PROGRESS)],
            [KeyboardButton(TEACHER_IMPERSONATE)],
            [KeyboardButton(TEACHER_LESSONS)],
            [KeyboardButton(ADD_STUDENT)],
        ],
        resize_keyboard=True,
    )


def teacher_lessons_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(TEACHER_CREATE_LESSON)],
            [KeyboardButton(TEACHER_MY_LESSONS)],
            [KeyboardButton("↩️ Teacher menu")],
        ],
        resize_keyboard=True,
    )


def training_keyboard(exchange: bool = False, game: bool = False) -> ReplyKeyboardMarkup:
    remember_text = KNOW if (exchange or game) else REMEMBER
    forget_text = DONT_KNOW if (exchange or game) else FORGET
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(SHOW_TRANSLATION)],
            [KeyboardButton(remember_text), KeyboardButton(forget_text)],
            [KeyboardButton(SKIP), KeyboardButton(STOP)],
        ],
        resize_keyboard=True,
    )


def answer_keyboard(can_correct: bool = False, can_confirm_correct: bool = False) -> ReplyKeyboardMarkup:
    rows = []
    if can_correct:
        rows.append([KeyboardButton(MISTAKE)])
    if can_confirm_correct:
        rows.append([KeyboardButton(I_WAS_RIGHT)])
    rows.extend(
        [
            [KeyboardButton(NEXT_CARD)],
            [KeyboardButton(STOP)],
        ]
    )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def text_input_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(DONT_KNOW)], [KeyboardButton(STOP)]], resize_keyboard=True)
