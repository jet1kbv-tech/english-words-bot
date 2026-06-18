# English Words Bot

MVP Telegram-бота для совместного изучения английских слов двумя пользователями: Вовой (`@wp_bvv`) и Сашей (`@privetnormalno`). Бот работает как отдельный Python-проект и может быть запущен локально или как отдельный `systemd`-сервис на сервере.

## Возможности

- Доступ только для разрешённых Telegram username при первом входе.
- После регистрации пользователь хранится и определяется по `telegram_id`, поэтому смена username не ломает доступ.
- Добавление слов и фраз с переводом, опциональной темой и примером.
- Массовое добавление слов списком.
- Удаление слов из личного словаря.
- Личный словарь пользователя с пагинацией по 10 слов в одном сообщении.
- Режим `🔄 Обмен словами`: пользователь тренирует слова партнёра, а незнакомые слова добавляются в его личный словарь.
- Тренировка по своим словам отдельным режимом `🎯 Мои карточки`.
- Отдельный прогресс для каждой пары `user_id` + `word_id`.
- SQLite-база создаётся автоматически при первом запуске.

## Структура проекта

```text
.
├── main.py
├── requirements.txt
├── .env.example
├── app
│   ├── config.py
│   ├── database.py
│   ├── keyboards.py
│   └── handlers
│       ├── start.py
│       ├── menu.py
│       ├── words.py
│       └── training.py
└── README.md
```

## Локальный запуск

Требуется Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env` реальным токеном Telegram-бота:

```dotenv
BOT_TOKEN=123456:replace-with-real-token
DATABASE_PATH=english_words_bot.sqlite3
LOG_LEVEL=INFO
```

Запуск:

```bash
python main.py
```

## Переменные окружения

| Переменная | Описание | Значение по умолчанию |
| --- | --- | --- |
| `BOT_TOKEN` | Telegram Bot API token. Обязательная переменная. | — |
| `DATABASE_PATH` | Путь до SQLite-файла. | `english_words_bot.sqlite3` |
| `LOG_LEVEL` | Уровень логирования Python. | `INFO` |
| `OPENAI_API_KEY` | Зарезервировано для будущих AI-функций. Сейчас не используется. | — |


## Seed Vova words

Одноразовый импорт списка слов в личный словарь Вовы (`@wp_bvv`). Перед запуском Вова должен открыть `/start` в боте, чтобы пользователь появился в базе. Скрипт читает `DATABASE_PATH` из `.env` и пропускает уже добавленные слова.

```bash
python scripts/seed_vova_words.py
```

## Запуск на сервере через systemd

Пример размещения проекта: `/opt/english-words-bot`.

```bash
cd /opt/english-words-bot
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Пример unit-файла `/etc/systemd/system/english-words-bot.service`:

```ini
[Unit]
Description=English Words Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/english-words-bot
EnvironmentFile=/opt/english-words-bot/.env
ExecStart=/opt/english-words-bot/.venv/bin/python main.py
Restart=always
RestartSec=5
User=englishbot
Group=englishbot

[Install]
WantedBy=multi-user.target
```

Команды управления сервисом:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now english-words-bot
sudo systemctl status english-words-bot
journalctl -u english-words-bot -f
```

## Схема SQLite

Бот создаёт таблицы:

- `users`: `id`, `telegram_id`, `username`, `display_name`, `created_at`, `updated_at`.
- `words`: `id`, `owner_user_id`, `english`, `translation`, `topic`, `example`, `created_at`, `updated_at`.
- `word_progress`: `id`, `user_id`, `word_id`, `score`, `times_seen`, `times_remembered`, `times_forgotten`, `last_reviewed_at`, `created_at`, `updated_at`, уникальная пара `(user_id, word_id)`.

## Команды и меню

- `/start` — регистрация/обновление пользователя и показ главного меню.
- `➕ Добавить слово` — пошаговое добавление слова.
- `📥 Добавить список слов` — массовое добавление слов из нескольких строк.
- `📚 Мой словарь` — только слова текущего пользователя, постранично по 10 слов; кнопки `⬅️ Назад` и `➡️ Далее` редактируют текущее сообщение.
- `🗑 Удалить` в личном словаре — показывает слова текущей страницы кнопками `🗑 1`, `🗑 2`, ... и удаляет только слова текущего пользователя после подтверждения.
- `🎯 Мои карточки` — тренировка по своим словам.
- `🔄 Обмен словами` — тренировка по словам партнёра: Вова видит слова Саши, Саша видит слова Вовы. Если нажать `❌ Не знаю`, слово копируется в личный словарь текущего пользователя без дублей по `owner_user_id + lower(english)`.
- `📊 Прогресс` — статистика текущего пользователя.

Карточки работают в двух направлениях и для каждой карточки направление выбирается случайно: English → Russian и Russian → English.

Во время личной тренировки доступны кнопки: `👀 Показать ответ`, `✅ Помню`, `❌ Не помню`, `⏭ Пропустить`, `🛑 Закончить`. В режиме обмена доступны кнопки: `👀 Показать ответ`, `✅ Знаю`, `❌ Не знаю`, `⏭ Пропустить`, `🛑 Закончить`.


## Future AI features

Планируемые возможности без текущего подключения OpenAI SDK и без реальных API-вызовов:

- автоперевод слова;
- генерация примеров;
- массовый импорт списка английских слов без переводов;
- автоматическое определение темы;
- мини-тесты и упражнения.
