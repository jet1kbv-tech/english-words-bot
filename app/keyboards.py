from telegram import KeyboardButton, ReplyKeyboardMarkup

ADD_WORD = "➕ Добавить слово"
BULK_ADD_WORDS = "📥 Добавить список слов"
MY_WORDS = "📚 Мой словарь"
ALL_WORDS = "👥 Общий словарь"
MY_CARDS = "🎯 Мои карточки"
ALL_CARDS = "🎲 Все карточки"
PROGRESS = "📊 Прогресс"
SHOW_TRANSLATION = "👀 Показать ответ"
REMEMBER = "✅ Помню"
FORGET = "❌ Не помню"
SKIP = "⏭ Пропустить"
STOP = "🛑 Закончить"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ADD_WORD), KeyboardButton(BULK_ADD_WORDS)],
            [KeyboardButton(MY_WORDS), KeyboardButton(ALL_WORDS)],
            [KeyboardButton(MY_CARDS)],
            [KeyboardButton(ALL_CARDS), KeyboardButton(PROGRESS)],
        ],
        resize_keyboard=True,
    )


def training_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(SHOW_TRANSLATION)],
            [KeyboardButton(REMEMBER), KeyboardButton(FORGET)],
            [KeyboardButton(SKIP), KeyboardButton(STOP)],
        ],
        resize_keyboard=True,
    )
