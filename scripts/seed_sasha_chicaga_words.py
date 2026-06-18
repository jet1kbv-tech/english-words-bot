from __future__ import annotations

import csv
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

USERNAME = "privetnormalno"
SOURCE_URL = "https://chicaga.ru/blog/1000_populyarnyh_slov_na_anglijskom/"
START_SECTION = "Слова на английском языке для расширения словарного запаса"
STOP_SECTION = "Частые ошибки в запоминании слов"

# Fallback for environments where the CHICAGA page is not reachable.
# Add tuples as: (topic, english, translation, example).
WORDS: tuple[tuple[str, str, str, str | None], ...] = ()


@dataclass(frozen=True)
class Word:
    topic: str
    english: str
    translation: str
    example: str | None = None


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "tr", "h2", "h3", "table"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "tr", "h2", "h3", "table"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def database_path() -> Path:
    load_dotenv()
    return Path(os.getenv("DATABASE_PATH", "english_words_bot.sqlite3"))


def clean_cell(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").strip().strip('"').split())


def parse_word_line(topic: str, line: str) -> list[Word]:
    if ";" not in line or line.startswith("Слово;"):
        return []
    try:
        cells = [clean_cell(cell) for cell in next(csv.reader([line], delimiter=";"))]
    except csv.Error:
        return []

    words: list[Word] = []
    for index in range(0, len(cells) - 3, 4):
        english, transcription, translation, example = cells[index : index + 4]
        if not english or not transcription.startswith("[") or not translation:
            continue
        words.append(Word(topic=topic, english=english, translation=translation, example=example or None))
    return words


def fetch_source_words() -> list[Word]:
    request = Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")

    extractor = TextExtractor()
    extractor.feed(html)

    words: list[Word] = []
    current_topic: str | None = None
    in_target_section = False

    for raw_line in extractor.text().splitlines():
        line = clean_cell(raw_line)
        if not line:
            continue
        if line == START_SECTION:
            in_target_section = True
            current_topic = None
            continue
        if not in_target_section:
            continue
        if line == STOP_SECTION:
            break
        if line.startswith("Слово;"):
            continue
        if ";" not in line:
            # Table titles are emitted as standalone text immediately before table rows.
            current_topic = line
            continue
        if current_topic is not None:
            words.extend(parse_word_line(current_topic, line))

    return words


def load_words() -> list[Word]:
    try:
        source_words = fetch_source_words()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        print(f"Could not load CHICAGA page, using embedded WORDS fallback: {error}")
        source_words = []

    if source_words:
        return source_words
    return [Word(topic=topic, english=english, translation=translation, example=example) for topic, english, translation, example in WORDS]


def main() -> int:
    db_path = database_path()
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        user = connection.execute("SELECT id FROM users WHERE username = ?", (USERNAME,)).fetchone()
        if user is None:
            print("User privetnormalno not found. Open /start in bot first.")
            return 1

        words = load_words()
        if not words:
            print("No words to seed. Fill WORDS in scripts/seed_sasha_chicaga_words.py and run again.")
            return 1

        owner_user_id = int(user["id"])
        added = 0
        skipped_duplicates = 0

        for word in words:
            english = word.english.strip()
            translation = word.translation.strip()
            duplicate = connection.execute(
                "SELECT 1 FROM words WHERE owner_user_id = ? AND lower(english) = lower(?) LIMIT 1",
                (owner_user_id, english),
            ).fetchone()
            if duplicate is not None:
                skipped_duplicates += 1
                continue

            now = utc_now()
            connection.execute(
                """
                INSERT INTO words (owner_user_id, english, translation, topic, example, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_user_id, english, translation, word.topic.strip(), word.example, now, now),
            )
            added += 1

        connection.commit()

    print(f"Loaded words: {len(words)}")
    print(f"Added: {added}")
    print(f"Skipped duplicates: {skipped_duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
