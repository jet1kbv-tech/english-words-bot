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

# Backward-compatible aliases for old imports / older Telegram keyboards.
ALL_WORDS = WORD_EXCHANGE
ALL_CARDS = WORD_EXCHANGE


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ADD_WORD), KeyboardButton(BULK_ADD_WORDS)],
            [KeyboardButton(MY_WORDS), KeyboardButton(WORD_EXCHANGE)],
            [KeyboardButton(MY_CARDS), KeyboardButton(GAME_SESSION)],
            [KeyboardButton(MY_MISTAKES), KeyboardButton(PROGRESS)],
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
