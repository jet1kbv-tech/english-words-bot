from telegram import KeyboardButton, ReplyKeyboardMarkup

ADD_WORD = "➕ Добавить слово"
BULK_ADD_WORDS = "📥 Добавить список слов"
MY_WORDS = "📚 Мой словарь"
WORD_EXCHANGE = "🔄 Обмен словами"
MY_CARDS = "🎯 Мои карточки"
GAME_SESSION = "🎮 Игра на 10 слов"
PROGRESS = "📊 Прогресс"
TEACHER_STUDENTS = "👤 Ученики"
TEACHER_ADD_WORD = "➕ Добавить слово ученику"
TEACHER_PROGRESS = "📊 Прогресс ученика"
TEACHER_VIEW_AS_STUDENT = "👀 Режим ученика"
EXIT_STUDENT_MODE = "↩️ Выйти из режима ученика"
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

# Backward-compatible aliases for old imports / older Telegram keyboards.
ALL_WORDS = WORD_EXCHANGE
ALL_CARDS = WORD_EXCHANGE


def main_menu_keyboard(include_exit_student_mode: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(ADD_WORD), KeyboardButton(BULK_ADD_WORDS)],
        [KeyboardButton(MY_WORDS), KeyboardButton(WORD_EXCHANGE)],
        [KeyboardButton(MY_CARDS), KeyboardButton(GAME_SESSION)],
        [KeyboardButton(PROGRESS)],
    ]
    if include_exit_student_mode:
        rows.append([KeyboardButton(EXIT_STUDENT_MODE)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def teacher_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(TEACHER_STUDENTS)],
            [KeyboardButton(TEACHER_ADD_WORD)],
            [KeyboardButton(TEACHER_PROGRESS)],
            [KeyboardButton(TEACHER_VIEW_AS_STUDENT)],
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
