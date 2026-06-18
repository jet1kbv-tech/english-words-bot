from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

USERNAME = "wp_bvv"
TOPIC = "Food & everyday English"
WORDS: tuple[tuple[str, str], ...] = (
    ("a keeper", "стоящая вещь / то, что стоит оставить"),
    ("not my cup of tea", "не моё / не в моём вкусе"),
    ("windmill", "ветряная мельница"),
    ("flakes", "хлопья"),
    ("canopy", "навес / крона"),
    ("subtle", "едва заметный / тонкий"),
    ("stale", "несвежий"),
    ("orangey", "апельсиновый / оранжеватый"),
    ("fizzy", "газированный / шипучий"),
    ("crispy", "хрустящий"),
    ("chocoholic", "любитель шоколада"),
    ("gingersnap", "имбирное печенье"),
    ("natural", "натуральный"),
    ("bottle opener", "открывалка для бутылок"),
    ("dry", "сухой"),
    ("shrimp", "креветка"),
    ("snack", "перекус / закуска"),
    ("sleeve", "рукав / упаковка-рукав"),
    ("lightly flavoured", "с лёгким вкусом"),
    ("spicy", "острый / пряный"),
    ("salted", "солёный"),
    ("pleasant", "приятный"),
    ("best by", "годен до / лучше употребить до"),
    ("pull tab", "язычок для открывания"),
    ("nailed", "справился / получилось идеально"),
    ("jelly", "желе"),
    ("clove", "гвоздика / зубчик чеснока"),
    ("carbonated", "газированный"),
    ("consider", "рассматривать / считать"),
    ("insisted", "настаивал"),
    ("twist off", "откручивающаяся крышка"),
    ("munching", "жевание / похрустывание"),
    ("filling", "сытный / начинка"),
    ("wrap", "ролл / завёрнутая лепёшка"),
    ("cheesy", "сырный"),
    ("yummy", "вкусный"),
    ("greasy", "жирный / маслянистый"),
    ("sugary", "сладкий / сахарный"),
    ("sweetness", "сладость"),
    ("crunchy", "хрустящий"),
    ("crunching", "хруст / хрустение"),
    ("flaky", "слоистый / рассыпчатый"),
    ("shortbread", "песочное печенье"),
    ("allergic", "аллергичный / с аллергией"),
    ("spread", "намазка / спред"),
    ("shiny", "блестящий"),
    ("bite-sized", "на один укус"),
    ("hazelnut", "фундук / лесной орех"),
    ("hoard", "запасать / копить"),
    ("worth it", "оно того стоит"),
    ("crust", "корочка"),
    ("to mush", "в кашу / размякнуть"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def database_path() -> Path:
    load_dotenv()
    return Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3"))


def main() -> int:
    db_path = database_path()
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        user = connection.execute("SELECT id FROM users WHERE username = ?", (USERNAME,)).fetchone()
        if user is None:
            print("User wp_bvv not found. Open /start in bot first.")
            return 1

        owner_user_id = int(user["id"])
        added = 0
        skipped_duplicates = 0

        for english, translation in WORDS:
            duplicate = connection.execute(
                "SELECT 1 FROM words WHERE owner_user_id = ? AND lower(english) = lower(?) LIMIT 1",
                (owner_user_id, english.strip()),
            ).fetchone()
            if duplicate is not None:
                skipped_duplicates += 1
                continue

            now = utc_now()
            connection.execute(
                """
                INSERT INTO words (owner_user_id, english, translation, topic, example, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (owner_user_id, english.strip(), translation.strip(), TOPIC, now, now),
            )
            added += 1

        connection.commit()

    print(f"Added: {added}")
    print(f"Skipped duplicates: {skipped_duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
