from telegram import KeyboardButton, ReplyKeyboardMarkup

ADD_WORD = "➕ Добавить слово"
BULK_ADD_WORDS = "📥 Добавить список слов"
MY_WORDS = "📚 Мой словарь"
WORD_EXCHANGE = "🔄 Обмен словами"
MY_CARDS = "🎯 Мои карточки"
PROGRESS = "📊 Прогресс"
SHOW_TRANSLATION = "👀 Показать ответ"
REMEMBER = "✅ Помню"
FORGET = "❌ Не помню"
KNOW = "✅ Знаю"
DONT_KNOW = "❌ Не знаю"
SKIP = "⏭ Пропустить"
NEXT_CARD = "➡️ Следующая карточка"
STOP = "🛑 Закончить"

# Backward-compatible aliases for old imports / older Telegram keyboards.
ALL_WORDS = WORD_EXCHANGE
ALL_CARDS = WORD_EXCHANGE


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(ADD_WORD), KeyboardButton(BULK_ADD_WORDS)],
            [KeyboardButton(MY_WORDS), KeyboardButton(WORD_EXCHANGE)],
            [KeyboardButton(MY_CARDS), KeyboardButton(PROGRESS)],
        ],
        resize_keyboard=True,
    )


def training_keyboard(exchange: bool = False) -> ReplyKeyboardMarkup:
    remember_text = KNOW if exchange else REMEMBER
    forget_text = DONT_KNOW if exchange else FORGET
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(SHOW_TRANSLATION)],
            [KeyboardButton(remember_text), KeyboardButton(forget_text)],
            [KeyboardButton(SKIP), KeyboardButton(STOP)],
        ],
        resize_keyboard=True,
    )


def answer_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(NEXT_CARD)],
            [KeyboardButton(STOP)],
        ],
        resize_keyboard=True,
    )
