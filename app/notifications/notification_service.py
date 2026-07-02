from __future__ import annotations

import logging

from app.database import Database
from app.lesson_metadata import lesson_display_name

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create_product_notification(self, key: str, role: str | None, title: str, body: str, feature_key: str | None = None, is_active: bool = True):
        return self.db.create_product_notification(key, role, title, body, feature_key, is_active)

    def list_active_product_notifications(self, role: str | None = None):
        return self.db.list_active_product_notifications(role)

    async def notify_lesson_assigned(self, bot, student_username: str, lesson) -> bool:
        student = self.db.get_user_by_username(student_username)
        if student is None:
            return False
        text = "\n".join([
            "📚 Вам назначен новый урок",
            "",
            lesson_display_name(lesson),
            "",
            "Откройте «Мои уроки», чтобы начать.",
        ])
        try:
            await bot.send_message(chat_id=int(student["telegram_id"]), text=text)
            return True
        except Exception:
            logger.exception("Failed to send lesson assignment notification to @%s", student_username)
            return False
