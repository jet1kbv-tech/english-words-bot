# Architecture: english-words-bot

Документ описывает текущую архитектуру `main` на момент анализа. Он фиксирует существующее поведение и правила разработки, но не вводит новых фич.

## 1. Назначение проекта

`english-words-bot` — Telegram-бот для двух пользователей, Вовы и Саши. Бот помогает вести личные словари английских слов, тренировать карточки, играть короткие игровые сессии на 10 слов, разбирать ошибки и обмениваться словами партнёра.

Точка входа — `main.py`: приложение загружает настройки, создаёт SQLite database layer, регистрирует обработчики Telegram-команд, conversation flows и callback query handlers, а также ежедневное напоминание через job queue.

## 2. Высокоуровневые компоненты

- `main.py` — сборка Telegram `Application`, регистрация handlers, создание `Database`, запуск polling, обработчик глобальных ошибок.
- `app/config.py` — загрузка `.env`, токена бота, пути к SQLite, уровня логирования, списка разрешённых usernames и display names.
- `app/database.py` — SQLite schema и все операции над пользователями, словами, прогрессом, игровыми сессиями и daily activity.
- `app/keyboards.py` — все тексты кнопок и reply keyboard layouts.
- `app/handlers/start.py` — авторизация пользователя и `/start`.
- `app/handlers/menu.py` — центральный router текстовых кнопок меню.
- `app/handlers/words.py` — добавление слов, bulk import, просмотр и удаление личного словаря.
- `app/handlers/training.py` — тренировки, game flow, разбор ошибок, обмен словами, прогресс, daily reminder.
- `app/ai/service.py` и `app/ai/polza_provider.py` — опциональная AI-проверка текстовых ответов в игровых сессиях.
- `scripts/seed_*.py` — вспомогательные scripts для наполнения словарей конкретных пользователей.
- `tests/` — unit tests для database и training logic.

## 3. Текущие меню

### 3.1 Главное меню

Главное меню строится в `main_menu_keyboard()` и состоит из 4 рядов:

1. `➕ Добавить слово` / `📥 Добавить список слов`
2. `📚 Мой словарь` / `🔄 Обмен словами`
3. `🎯 Мои карточки` / `🎮 Игра на 10 слов`
4. `😵 Мои ошибки` / `📊 Прогресс`

Все тексты кнопок объявлены константами в `app/keyboards.py`. Роутинг этих кнопок находится в `app/handlers/menu.py`.

### 3.2 Меню тренировки с self-check

`training_keyboard(exchange=False, game=False)` используется для обычных карточек и обмена словами, когда пользователь сам отмечает результат.

Кнопки:

- `👀 Показать ответ`
- Для обычной тренировки: `✅ Помню` / `❌ Не помню`
- Для обмена или игры в self-check режиме: `✅ Знаю` / `❌ Не знаю`
- `⏭ Пропустить` / `🛑 Закончить`

### 3.3 Меню после ответа

`answer_keyboard()` используется после выставления результата карточки или после текстового ответа.

Возможные кнопки:

- `😬 Ошибся` — появляется после положительного self-check ответа, чтобы исправить его на отрицательный.
- `😬 Я был прав` — появляется после отрицательного текстового ответа, чтобы исправить его на положительный.
- `➡️ Следующая карточка`
- `🛑 Закончить`

### 3.4 Меню текстового ввода в игре

`text_input_keyboard()` используется в игровых сессиях, где пользователь должен написать перевод в чат.

Кнопки:

- `❌ Не знаю`
- `🛑 Закончить`

### 3.5 Inline-меню словаря

Просмотр словаря использует inline keyboard:

- `⬅️ Назад` / `➡️ Далее` — постраничная навигация.
- `🗑 Удалить` — переход в режим выбора слова для удаления.
- `↩️ В меню` — возврат к главному reply menu.

В режиме удаления:

- `🗑 1`, `🗑 2`, ... — выбор слова на текущей странице.
- `↩️ Назад`
- `↩️ В меню`

На подтверждении удаления:

- `✅ Да, удалить`
- `↩️ Отмена`

## 4. Роли и доступ

### 4.1 Пользовательские роли

В коде нет отдельной RBAC-модели. Есть два разрешённых Telegram username:

- `wp_bvv` → display name `Вова`
- `privetnormalno` → display name `Саша`

Доступ к боту разрешён только этим пользователям. Все остальные получают отказ при `/start` или при попытке пройти `require_user()`.

### 4.2 Владение данными

Основная граница доступа — `users.id` и `words.owner_user_id`.

- Личный словарь показывает только слова текущего пользователя.
- Удалять можно только свои слова через `get_owned_word()` и `delete_word()`.
- Обычная тренировка, игра на 10 слов и ошибки используют только собственные слова пользователя.
- Обмен словами показывает слова партнёра, исключая слова, которые уже есть у текущего пользователя по case-insensitive совпадению `english`.
- Если в обмене пользователь отмечает слово партнёра как незнакомое, бот копирует это слово в личный словарь пользователя.

## 5. Словари

### 5.1 Модель слова

Слово хранится в таблице `words` и содержит:

- `owner_user_id` — владелец слова.
- `english` — английское слово или фраза.
- `translation` — перевод.
- `topic` — необязательная тема.
- `example` — необязательный пример.
- `created_at`, `updated_at`.

Дубликат считается в рамках одного владельца по `lower(english)`. Разные пользователи могут иметь одинаковые слова в своих словарях.

### 5.2 Добавление одного слова

Conversation flow `➕ Добавить слово`:

1. Запрашивается английское слово или фраза.
2. Запрашивается перевод.
3. Запрашивается тема; `-` или пустое значение означает отсутствие темы.
4. Запрашивается пример; `-` или пустое значение означает отсутствие примера.
5. Слово добавляется через `Database.add_word()`; дубль не добавляется.

Fallbacks conversation: `/cancel` и `/start`.

### 5.3 Bulk import

Conversation flow `📥 Добавить список слов` принимает список строк. Поддержанные разделители:

- `english — translation`
- `english - translation`
- `english: translation`
- `english = translation`

Пустые и нераспознанные строки пропускаются. Дубли внутри одного сообщения отсеиваются по `english.casefold()`. Дубли в БД отсеиваются через `Database.add_word()`.

### 5.4 Просмотр и удаление словаря

`📚 Мой словарь` показывает только личные слова пользователя, по 10 слов на страницу. Слова сортируются по `created_at DESC, id DESC`.

Удаление защищено двумя проверками:

1. Callback word id должен присутствовать на текущей странице словаря.
2. Слово должно принадлежать текущему пользователю.

При удалении сначала удаляется `word_progress` по `word_id`, затем запись из `words`.

### 5.5 Обмен словами

`🔄 Обмен словами` берёт слова других пользователей, которых ещё нет у текущего пользователя. Это не отдельный словарь, а режим тренировки поверх чужих слов. Если пользователь отмечает чужое слово как незнакомое, оно копируется в его личный словарь.

## 6. Game flow и тренировки

### 6.1 Общие понятия session state

Текущее состояние тренировки хранится в `context.user_data["training"]`. Основные поля:

- `words` — текущий список карточек.
- `directions` — направление перевода для каждой карточки.
- `index` — текущая позиция.
- `exchange` — режим обмена словами.
- `game` — игровой режим с текстовым вводом и summary.
- `mistakes` — специальная игровая сессия для ошибок.
- `session_id` — id строки `study_sessions` для игровых сессий.
- `known`, `unknown`, `remembered_count`, `forgotten_count`, `skipped` — счётчики.
- `xp_earned` — XP текущей игровой сессии.
- `awaiting_text_input` — ожидание текстового ответа в игре.
- `last_positive_answer` / `last_negative_text_answer` — данные для исправления последнего результата.

Направления карточек:

- `EN_TO_RU` — показать английское, ожидать русский перевод.
- `RU_TO_EN` — показать перевод, ожидать английское слово.

Направление выбирается случайно и сохраняется на индекс карточки, чтобы повторное отображение той же карточки не меняло направление.

### 6.2 Обычная тренировка: `🎯 Мои карточки`

- Использует только личные слова пользователя.
- Слова сортируются weighted random order: новые и слабые слова получают больший вес.
- Пользователь может показать ответ и сам отметить `Помню` / `Не помню` / `Пропустить`.
- Каждая отметка обновляет `word_progress`.
- После `Помню` доступна кнопка `😬 Ошибся`, которая корректирует уже записанный положительный ответ в отрицательный без увеличения `times_seen`.

### 6.3 Игра на 10 слов: `🎮 Игра на 10 слов`

- Использует только личные слова пользователя.
- Размер сессии — `GAME_SESSION_SIZE = 10`.
- Подбор слов: преимущественно новые и слабые карточки плюс небольшая доля сильных карточек для повторения.
- Создаётся запись `study_sessions`.
- Пользователь вводит ответ текстом в чат.
- В игровом режиме проверка ответа сначала пытается использовать AI provider; если AI недоступен или вернул `None`, используется локальная строгая проверка.
- `❌ Не знаю` в режиме ожидания текстового ответа сразу записывает отрицательный результат и показывает полный ответ.
- По завершении начисляется bonus XP за завершение сессии, обновляются `study_sessions` и `daily_activity`, выводится summary.

XP в текущей реализации:

- правильный ответ: `10`
- неправильный ответ: `2`
- завершение сессии: `25`

Daily goal:

- цель дня: `10` карточек.
- уровни дня: `Разогрев`, `Цель выполнена`, `Сильный день`, `Легенда дня`.

### 6.4 Мои ошибки: `😵 Мои ошибки`

- Использует личные слова пользователя.
- Выбирает слова с низким score или с количеством забываний больше количества успешных ответов.
- Если ошибок меньше лимита, добирает карточки через обычный smart review алгоритм.
- Дальше flow совпадает с игровой сессией: текстовый ввод, `study_sessions`, daily activity, XP, summary.

### 6.5 Обмен словами: `🔄 Обмен словами`

- Использует слова партнёра, которых ещё нет в личном словаре текущего пользователя.
- Flow похож на self-check тренировку.
- Если пользователь отмечает слово как незнакомое, слово копируется в его словарь.
- При исправлении `😬 Ошибся` после положительного ответа в обмене слово тоже копируется в личный словарь.

### 6.6 Исправления ответов

Есть два типа исправлений:

- `😬 Ошибся`: положительный ответ превращается в отрицательный через `correct_remembered_to_forgotten()`.
- `😬 Я был прав`: отрицательный текстовый ответ превращается в положительный через `correct_forgotten_to_remembered()`.

Обе коррекции не увеличивают `times_seen`, потому что карточка уже была засчитана как увиденная при первом ответе.

## 7. AI

AI используется только для проверки текстовых ответов в игровых сессиях (`game=True`). Обычная тренировка и exchange self-check не используют AI.

### 7.1 Provider selection

`check_text_answer()` смотрит переменную окружения `AI_PROVIDER`.

- По умолчанию используется `polza`.
- Если значение не `polza`, функция возвращает `None`.

### 7.2 Polza provider

`PolzaAIProvider` использует OpenAI-compatible client `AsyncOpenAI` с параметрами:

- `POLZA_API_KEY` — ключ, без него provider недоступен.
- `POLZA_BASE_URL` — по умолчанию `https://polza.ai/api/v1`.
- `AI_MODEL` — по умолчанию `deepseek/deepseek-v4-flash`.

Provider просит модель вернуть JSON:

- `is_correct: boolean`
- `feedback: string`

Если client недоступен, нет ключа, произошла ошибка API, JSON не распарсился или schema ответа неверная, provider возвращает `None`.

### 7.3 Fallback logic

Если AI вернул `None`, применяется локальная проверка:

- Ответ нормализуется: lower-case, замена `ё` на `е`, схлопывание пробелов, trim.
- В направлении `RU_TO_EN` ответ должен точно совпасть с `english` после нормализации.
- В направлении `EN_TO_RU` ответ должен совпасть с одним из вариантов `translation`, разделённых `/`, `,`, `;`.

## 8. Database tables

SQLite schema создаётся в `Database.init_schema()`.

### 8.1 `users`

Пользователи Telegram.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | internal id |
| `telegram_id` | INTEGER NOT NULL UNIQUE | Telegram user id |
| `username` | TEXT NOT NULL | normalized username without `@` |
| `display_name` | TEXT NOT NULL | display name из настроек |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

### 8.2 `words`

Личные слова пользователей.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | word id |
| `owner_user_id` | INTEGER NOT NULL | FK → `users(id)`, `ON DELETE CASCADE` |
| `english` | TEXT NOT NULL | слово/фраза |
| `translation` | TEXT NOT NULL | перевод |
| `topic` | TEXT | optional |
| `example` | TEXT | optional |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

Важно: в таблице нет SQL `UNIQUE(owner_user_id, lower(english))`; дубли предотвращаются application-level методом `word_exists()`.

### 8.3 `word_progress`

Прогресс конкретного пользователя по конкретному слову.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | progress id |
| `user_id` | INTEGER NOT NULL | FK → `users(id)` |
| `word_id` | INTEGER NOT NULL | FK → `words(id)` |
| `score` | INTEGER NOT NULL DEFAULT 0 | растёт при remembered, не ниже 0 при forgotten |
| `times_seen` | INTEGER NOT NULL DEFAULT 0 | сколько раз карточка была засчитана |
| `times_remembered` | INTEGER NOT NULL DEFAULT 0 | успешные ответы |
| `times_forgotten` | INTEGER NOT NULL DEFAULT 0 | неуспешные ответы |
| `last_reviewed_at` | TEXT | UTC ISO string |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

Constraint: `UNIQUE(user_id, word_id)`.

### 8.4 `study_sessions`

Игровые сессии на 10 слов и сессии ошибок.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | session id |
| `user_id` | INTEGER NOT NULL | FK → `users(id)` |
| `total_cards` | INTEGER NOT NULL | размер сессии |
| `known_cards` | INTEGER NOT NULL DEFAULT 0 | итоговое количество known |
| `unknown_cards` | INTEGER NOT NULL DEFAULT 0 | итоговое количество unknown |
| `skipped_cards` | INTEGER NOT NULL DEFAULT 0 | пропуски |
| `started_at` | TEXT NOT NULL | UTC ISO string |
| `finished_at` | TEXT | UTC ISO string после завершения |

### 8.5 `daily_activity`

Агрегаты активности за день по пользователю.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | activity id |
| `user_id` | INTEGER NOT NULL | FK → `users(id)` |
| `activity_date` | TEXT NOT NULL | дата в Moscow timezone, `YYYY-MM-DD` |
| `cards_reviewed` | INTEGER NOT NULL DEFAULT 0 | known + unknown, skipped не входит |
| `known_cards` | INTEGER NOT NULL DEFAULT 0 | сумма known |
| `unknown_cards` | INTEGER NOT NULL DEFAULT 0 | сумма unknown |
| `skipped_cards` | INTEGER NOT NULL DEFAULT 0 | сумма skipped |
| `xp_earned` | INTEGER NOT NULL DEFAULT 0 | сумма XP |
| `streak_days` | INTEGER NOT NULL DEFAULT 0 | streak на дату |
| `day_level` | TEXT NOT NULL DEFAULT `Разогрев` | уровень дня |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

Constraint: `UNIQUE(user_id, activity_date)`.

`init_schema()` дополнительно вызывает migration helper `_ensure_daily_activity_xp_column()` для старых баз без `xp_earned`.

## 9. Правила добавления новых features

1. **Не добавлять feature без явного сценария.** Сначала описать user flow: какая кнопка, какой handler, какое состояние в `context.user_data`, какие изменения в БД.
2. **Держать тексты кнопок в `app/keyboards.py`.** Не размазывать literals кнопок по handlers; `menu_message()` должен сравнивать текст с константами.
3. **Новый пункт главного меню = три изменения минимум:** константа и layout в `app/keyboards.py`, ветка router в `app/handlers/menu.py`, handler в соответствующем модуле.
4. **Conversation flow регистрировать в `main.py`.** Для многошагового ввода использовать `ConversationHandler` с понятными states и fallbacks `/cancel`, `/start`.
5. **DB changes делать через `Database`.** Не писать SQL в handlers, если это не маленькая read-only проверка уже существующего паттерна. Для новых сущностей добавить methods в `app/database.py` и tests.
6. **Сохранять owner isolation.** Любая операция над словами должна учитывать текущего `user["id"]`; удаление и редактирование должны проверять ownership.
7. **Не ломать exchange semantics.** Чужие слова не становятся личными, пока пользователь явно не отметил их как незнакомые или не исправил положительный ответ в отрицательный.
8. **Не смешивать game и self-check.** Game ожидает текстовый ответ и может использовать AI; self-check использует кнопки `Показать ответ` + `Помню/Не помню` или `Знаю/Не знаю`.
9. **Сохранять fallback без AI.** Любая AI-зависимая feature должна корректно работать при отсутствии ключа, пакета `openai`, сетевого доступа или валидного ответа provider.
10. **Тестировать чистую логику.** Алгоритмы выбора карточек, нормализацию ответов, DB updates и corrections должны иметь unit tests в `tests/`.
11. **Сохранять существующие public button texts или обеспечить backward compatibility.** У старых пользователей в Telegram может остаться старая клавиатура; для переименований нужны aliases или transitional handling.
12. **Не хранить secrets в коде.** Новые настройки добавлять через `.env` / `.env.example` и `load_settings()` или точечно через `os.getenv`, если это provider-level настройка.

## 10. Как избегать конфликтов

### 10.1 Файлы с высокой вероятностью конфликтов

- `app/keyboards.py` — центральное место всех кнопок и layout главного меню.
- `app/handlers/menu.py` — central router всех текстовых действий.
- `main.py` — регистрация handlers и conversations.
- `app/database.py` — schema и DB API.
- `app/handlers/training.py` — самый плотный файл с game flow и session state.

Перед изменениями в этих файлах стоит проверить, не меняет ли параллельная ветка те же участки.

### 10.2 Рекомендованный порядок для новых changes

1. Добавить или изменить чистую функцию/DB method с тестом.
2. Подключить handler flow.
3. Подключить кнопку и routing.
4. Зарегистрировать conversation/callback handler в `main.py`, если нужно.
5. Обновить документацию (`README.md` или этот файл), если меняется пользовательский flow или архитектурное правило.

Такой порядок снижает риск конфликтов в `keyboards.py`, `menu.py` и `main.py`, потому что интеграционные правки делаются в конце и становятся маленькими.

### 10.3 Правила работы с callback data

- Callback prefixes должны быть уникальными (`dict_page`, `dict_delete_page`, `confirm_delete_word`, ...).
- Pattern в `main.py` должен быть достаточно строгим, чтобы handler не перехватывал чужие callbacks.
- Callback payload должен содержать только минимальные ids/page numbers; ownership всегда проверяется на сервере через DB.

### 10.4 Правила работы с session state

- Все поля training state должны быть задокументированы рядом с flow или в этом файле.
- Не использовать одно и то же поле для разных смыслов в разных режимах.
- При завершении flow очищать `context.user_data["training"]` или временные поля (`new_word`, `bulk_words`, `awaiting_text_input`).
- При correction не увеличивать `times_seen`, если исходный ответ уже был засчитан.

### 10.5 Правила миграций

- `CREATE TABLE IF NOT EXISTS` подходит для новых установок, но не меняет существующие таблицы.
- Для новых колонок нужен helper по образцу `_ensure_daily_activity_xp_column()`.
- Не удалять и не переименовывать колонки без отдельного migration plan.
- Для constraints, которые SQLite не может добавить простым `ALTER TABLE`, нужен явный план rebuild таблицы и backup strategy.

### 10.6 Правила тестов перед merge

Минимальный набор проверок после изменений:

```bash
python -m unittest
```

Если менялась логика выбора карточек или проверки ответа — дополнить `tests/test_training.py`.
Если менялась schema или DB behavior — дополнить `tests/test_database.py`.
