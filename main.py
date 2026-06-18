from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.config import load_settings
from app.database import Database
from app.handlers.menu import menu_message
from app.handlers.start import start
from app.handlers.words import BULK_WORDS, ENGLISH, EXAMPLE, TOPIC, TRANSLATION, add_word_start, bulk_add_words_start, bulk_words_step, cancel_add_word, confirm_delete_word, delete_word_prompt, dictionary_delete_page, dictionary_menu, dictionary_page, english_step, example_step, topic_step, translation_step
from app.keyboards import ADD_WORD, BULK_ADD_WORDS


MOSCOW_TZ = ZoneInfo("Europe/Moscow")


async def daily_game_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    today = datetime.now(MOSCOW_TZ).date()
    for user in db.list_registered_users():
        if db.has_completed_session_on(user["id"], today):
            continue
        await context.bot.send_message(
            chat_id=user["telegram_id"],
            text="👋 Пора на короткую сессию английского?\n10 слов — и streak продолжится 🔥",
        )


def schedule_daily_reminder(application: Application) -> None:
    if application.job_queue is None:
        logging.warning("JobQueue is not available; install python-telegram-bot[job-queue] to enable daily reminders.")
        return
    application.job_queue.run_daily(
        daily_game_reminder,
        time=time(hour=14, minute=0, tzinfo=MOSCOW_TZ),
        name="daily_game_reminder",
    )


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

    bulk_add_words_conversation = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BULK_ADD_WORDS}$"), bulk_add_words_start)],
        states={BULK_WORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_words_step)]},
        fallbacks=[CommandHandler("cancel", cancel_add_word), CommandHandler("start", start)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_word_conversation)
    application.add_handler(bulk_add_words_conversation)
    application.add_handler(CallbackQueryHandler(dictionary_page, pattern=r"^dict_page:\d+$"))
    application.add_handler(CallbackQueryHandler(dictionary_delete_page, pattern=r"^dict_delete_page:\d+$"))
    application.add_handler(CallbackQueryHandler(delete_word_prompt, pattern=r"^dict_delete_word:\d+:\d+$"))
    application.add_handler(CallbackQueryHandler(confirm_delete_word, pattern=r"^confirm_delete_word:\d+:\d+$"))
    application.add_handler(CallbackQueryHandler(dictionary_menu, pattern=r"^dict_menu$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
    schedule_daily_reminder(application)
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
