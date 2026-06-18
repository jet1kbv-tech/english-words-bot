from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters

from app.config import load_settings
from app.database import Database
from app.handlers.menu import menu_message
from app.handlers.start import start
from app.handlers.words import ENGLISH, EXAMPLE, TOPIC, TRANSLATION, add_word_start, cancel_add_word, english_step, example_step, topic_step, translation_step
from app.keyboards import ADD_WORD


async def error_handler(update: object, context) -> None:
    logging.exception("Unhandled bot error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Произошла ошибка. Попробуйте ещё раз или вернитесь в меню командой /start.")


def build_application() -> Application:
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = Database(settings.database_path)
    db.init_schema()

    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db

    add_word_conversation = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{ADD_WORD}$"), add_word_start)],
        states={
            ENGLISH: [MessageHandler(filters.TEXT & ~filters.COMMAND, english_step)],
            TRANSLATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, translation_step)],
            TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, topic_step)],
            EXAMPLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, example_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_word), CommandHandler("start", start)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_word_conversation)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    application = build_application()
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        application.bot_data["db"].close()


if __name__ == "__main__":
    main()
