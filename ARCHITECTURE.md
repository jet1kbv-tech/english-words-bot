# Architecture: english-words-bot

Документ описывает текущую архитектуру `main` на момент анализа. Он фиксирует существующее поведение и правила разработки, но не вводит новых фич.

## 1. Назначение проекта

`english-words-bot` — Telegram-бот для двух пользователей, Вовы и Саши. Бот помогает вести личные словари английских слов, тренировать карточки, играть короткие игровые сессии на 10 слов, разбирать ошибки и обмениваться словами партнёра.

Точка входа — `main.py`: приложение загружает настройки, создаёт SQLite database layer, регистрирует обработчики Telegram-команд, conversation flows и callback query handlers, а также ежедневное напоминание через job queue.

## 2. Высокоуровневые компоненты

- `main.py` — сборка Telegram `Application`, регистрация handlers, создание `Database`, запуск polling, обработчик глобальных ошибок.
- `app/config.py` — загрузка `.env`, токена бота, пути к SQLite, уровня логирования, списков разрешённых/role-based usernames и display names.
- `app/auth/roles.py` — RoleResolver: enum ролей и централизованная проверка доступа по username.
- `app/database.py` — SQLite schema и все операции над пользователями, словами, прогрессом, игровыми сессиями, daily activity и черновиками уроков.
- `app/student_access_service.py` — нормализация и валидация Telegram usernames, а также сервис добавления dynamic student access без SQL в handlers.
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

Главное меню строится в `main_menu_keyboard()` и состоит из:

1. `📚 Мои уроки` — отдельной строкой сверху.
2. `➕ Добавить слово` / `📥 Добавить список слов`
3. `📚 Мой словарь` / `🔄 Обмен словами`
4. `🎯 Мои карточки` / `🎮 Игра на 10 слов`
5. `😵 Мои ошибки` / `📊 Прогресс`
6. `❓ Помощь`

Плюс `🛠 Админ` для `ADMIN` и `↩️ Выйти из режима ученика` в impersonation-режиме.

Все тексты кнопок объявлены константами в `app/keyboards.py`. Роутинг этих кнопок находится в `app/handlers/menu.py`, `app/handlers/student_lessons.py` (`Мои уроки`) и `app/tutorial/tutorial_service.py` (`Помощь`).

`Мои уроки` — дополнительная точка входа к урокам, назначенным учителем; она не заменяет и не скрывает базовый функционал (словарь, карточки, игра, ошибки, обмен), который остаётся основным способом занятий, пока раздел Lessons не умеет запускать реальную тренировку слов урока (см. 3.8 и 8.6.5).

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


### 3.6 Teacher lessons menu

Teacher menu содержит кнопку `📚 Уроки`. Внутри раздела доступны:

- список lessons с пустым состоянием, кнопками открытия `Lesson <id>`, `➕ Создать lesson` и `⬅️ Назад`;
- `➕ Создать lesson` — teacher вводит название урока, после чего создаётся draft lesson и сразу показывается detail screen;
- при создании сохраняется backward-compatible `title`, а lightweight parser пытается заполнить metadata `lesson_number` и `topic` из форматов вроде `Lesson 15 — Food`, `Lesson 15 - Food`, `15 — Food`, `15 - Food` или `Food`;
- lesson detail организован как секции `📖 Слова`, `📝 Грамматика`, `✏️ Упражнения`, `🏠 Домашнее задание`, `🤖 AI-помощник`; экран показывает display name, статус, metadata `Тема`/`Уровень`/`Описание` и реальные counts для слов/грамматики/упражнений/домашнего задания. UI-подписи teacher-раздела русифицированы; формат имени урока (`Lesson 15 — Food`) сохранён, потому что в этом же формате учитель вводит название и работает парсер `parse_lesson_title`.

Этот UI не публикует уроки, не вызывает AI-генерацию и не меняет game flow.

## 4. Роли и доступ

### 4.1 Пользовательские роли

Роли централизованы в `app/auth/roles.py`. RoleResolver содержит enum `Role`:

- `ADMIN`
- `TEACHER`
- `STUDENT`

`get_user_role(username, config)` нормализует Telegram username без `@` и сравнивает его case-insensitive:

1. username из `admin_usernames` получает `ADMIN`;
2. username из `teacher_usernames` получает `TEACHER`;
3. все остальные usernames получают `STUDENT`.

`is_user_allowed(username, config, db)` разрешает доступ, если username есть в объединении `allowed_usernames`, `admin_usernames`, `teacher_usernames` или в `student_access` с `is_active = 1`. Student access can be granted dynamically by teachers via the `student_access` table. Env-based access remains supported. Role priority: admin → teacher → student. `None` и пустые usernames не падают и не получают доступ. Роль при этом остаётся конфигурационной: admin usernames → `ADMIN`, teacher usernames → `TEACHER`, остальные разрешённые пользователи → `STUDENT`.

`admin_usernames`, `teacher_usernames`, `allowed_usernames` и `display_names` в `Settings` читаются из `.env` (`ADMIN_USERNAMES`, `TEACHER_USERNAMES`, `ALLOWED_USERNAMES`, `DISPLAY_NAMES` — списки через запятую, `DISPLAY_NAMES` в формате `username:Имя`) в `app/config.py::load_settings()`. Если переменная не задана, используется fallback-константа с тем же значением, что было захардкожено раньше:

- `wp_bvv` → `ADMIN`, display name `Вова`
- `romateaches` → `TEACHER`, display name `Roma`
- `privetnormalno` → `STUDENT`, display name `Саша`

`RoleResolver` не знает, откуда взялись эти значения — он просто читает атрибуты `config`, поэтому смена источника (хардкод → `.env`) не потребовала изменений в `app/auth/roles.py`.

`ADMIN` получает обычное student menu с дополнительной кнопкой `🛠 Админ`; `TEACHER` получает отдельное teacher menu с разделом `📚 Уроки` и кнопкой `➕ Добавить ученика`. Admin menu тоже содержит `➕ Добавить ученика`. Тренировки, игра на 10 слов, ошибки и обмен словами остаются прежними и работают через `require_user()`. Все остальные получают отказ при `/start` или при попытке пройти `require_user()`.

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

## 8.6 Lessons

Lesson is the central learning entity. Роли по-прежнему определяются существующим `RoleResolver`; teacher lesson UI сейчас подключает только минимальные list/create/detail screens без student lesson flow, AI-проверки или генерации упражнений.

Current Lesson lifecycle:

- `DRAFT`

Future statuses:

- `PUBLISHED`
- `ARCHIVED`

Teacher Lesson UI currently supports listing and creating draft lessons. Teacher Lesson Detail is organized as sections: Слова, Грамматика, Упражнения, Домашнее задание, AI-помощник (labels russified). Слова, Грамматика, Упражнения and Домашнее задание have real list/add/detail/delete screens (manual content only); AI-помощник remains a navigation placeholder — AI-assisted content generation is a separate future PR.

В будущем урок будет связывать четыре направления данных:

- `words` — слова и фразы, выбранные для урока;
- grammar — тема и грамматический фокус урока;
- homework — ручные задания к уроку;
- reports — будущие отчёты по выполнению и прогрессу.

### 8.6.1 `lessons`

Базовая запись урока для одного ученика и опционального учителя.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | lesson id |
| `teacher_user_id` | INTEGER | optional teacher user id |
| `student_user_id` | INTEGER | optional student user id; nullable for teacher-created lesson skeleton drafts |
| `title` | TEXT NOT NULL | backward-compatible original teacher input |
| `lesson_number` | INTEGER NULL | optional lesson number parsed from teacher input |
| `topic` | TEXT NULL | optional topic parsed from teacher input or set to full input when number is absent |
| `description` | TEXT NULL | optional lesson description metadata |
| `level` | TEXT NULL | optional lesson level metadata |
| `theme` | TEXT | optional lexical/theme focus |
| `grammar_topic` | TEXT | optional grammar focus |
| `status` | TEXT NOT NULL DEFAULT `DRAFT` | lifecycle status |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

Lesson keeps backward-compatible `title`, but now also has metadata fields: `lesson_number`, `topic`, `description`, `level`. Display name is derived from metadata when possible: `Lesson {lesson_number} — {topic}`, or `topic`, or fallback `title`.

### 8.6.2 `lesson_words`

Связующая таблица между уроками и существующими словами.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | link id |
| `lesson_id` | INTEGER NOT NULL | lesson id |
| `word_id` | INTEGER NOT NULL | word id from `words` |
| `created_at` | TEXT NOT NULL | UTC ISO string |

Constraint: `UNIQUE(lesson_id, word_id)`, поэтому повторное добавление того же слова в тот же урок игнорируется database method `add_word_to_lesson()`.

### 8.6.3 `homework_tasks`

Задания к уроку. Teacher UI (Phase 4, step 2) умеет создавать, просматривать и удалять задания трёх типов; AI-генерация заданий не добавлена.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | task id |
| `lesson_id` | INTEGER NOT NULL | lesson id |
| `task_type` | TEXT NOT NULL | `translation` \| `free` \| `quiz` |
| `prompt` | TEXT NOT NULL | текст задания / вопрос |
| `expected_answer` | TEXT | для `translation` — опциональный эталонный перевод; для `quiz` — текст правильного варианта; для `free` не используется |
| `metadata_json` | TEXT | только для `quiz`: `{"options": [...], "correct_index": N}` |
| `order_index` | INTEGER NOT NULL DEFAULT 0 | порядок в списке урока, назначается автоматически при создании (`Database.list_homework_tasks()` + 1) |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

Типы заданий (`app/lesson_service.py`):

- **`translation`** — учитель задаёт слово/фразу и опционально эталонный перевод; ученик пишет перевод в чат, ответ проверяется `check_translation_task_answer()` (`app/handlers/training.py`) — тем же AI+fallback механизмом, что и `🎮 Игра на 10 слов` (direction всегда `EN_TO_RU`: `prompt` — английское слово, ответ ученика — русский перевод). Если AI недоступен и `expected_answer` не задан, авто-проверка невозможна — ответ уходит в `⏳` (нужна ручная проверка), как `free`.
- **`free`** — открытый вопрос без автопроверки; ответ ученика всегда сохраняется с `is_correct = NULL` (⏳ на проверке); ручная проверка учителем (4.2c) пока не реализована.
- **`quiz`** — вопрос с 2–6 вариантами ответа; варианты и индекс правильного хранятся в `metadata_json`, `expected_answer` дублирует текст правильного варианта для удобства отображения. Ученик выбирает вариант inline-кнопкой, проверка мгновенная (сравнение индексов, без AI).

Teacher UI: `🏠 Домашнее задание` внутри урока показывает список заданий (`TEACHER_LESSON_HOMEWORK_PREFIX`), `➕ Добавить задание` → выбор типа (`TEACHER_LESSON_HOMEWORK_ADD_PREFIX` / `_ADD_TYPE_PREFIX`) → многошаговый текстовый ввод через `context.user_data["teacher_action"] = "teacher_create_homework_task"` и `_PENDING_HOMEWORK_TASK` (аналогично flow создания урока/импорта слов). Просмотр задания (`_OPEN_PREFIX`) → `🗑 Удалить` с подтверждением (`_DELETE_PREFIX` → `_DELETE_CONFIRM_PREFIX`), симметрично удалению слов словаря. Удаление задания каскадно удаляет связанные `homework_answers`.

Редактирование уже созданного задания (кроме удаления) в этом шаге не добавлено — только создание, просмотр, удаление.

### 8.6.4 `homework_answers`

Ответы учеников на задания урока (Phase 4, step 3). Каждая отправка ответа — новая строка (append-only, без `UNIQUE(task_id, user_id)`); текущий статус задания в списке ученика определяется по последней строке для пары `(task_id, user_id)` — `Database.list_latest_homework_answers(lesson_id, user_id)` берёт последнюю запись на задание одним запросом вместо N+1.

Ручная проверка учителем (Phase 4, step 4): `Database.review_homework_answer(answer_id, is_correct, feedback)` обновляет конкретную строку ответа на месте (не вставляет новую) — `is_correct`/`feedback`, изначально `NULL`, выставляются учителем. Teacher UI: экран задания (`app/handlers/teacher.py`) подтягивает последний ответ назначенного ученика (`Database.get_latest_homework_answer`) и, если он ещё `⏳` (`is_correct IS NULL`), показывает кнопки `✅ Верно` / `❌ Неверно`; после нажатия — один опциональный шаг текстом («Добавить комментарий ученику? Напишите текст, или отправьте '-' чтобы пропустить», состояние `context.user_data["teacher_action"] = "teacher_review_homework_answer"` + `pending_homework_review`), после которого оценка и комментарий сохраняются вместе. Список заданий учителя и ученика используют одну и ту же иконку статуса (⚪/✅/❌/⏳).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | answer id |
| `task_id` | INTEGER NOT NULL | homework task id |
| `user_id` | INTEGER NOT NULL | answering user id |
| `answer` | TEXT NOT NULL | ответ ученика |
| `is_correct` | INTEGER | `NULL` — ждёт проверки (⏳); `0`/`1` — авто- или ручной результат (❌/✅) |
| `feedback` | TEXT | optional feedback |
| `created_at` | TEXT NOT NULL | UTC ISO string |

Student UI (`app/handlers/student_lessons.py`): экран обзора урока показывает кнопку `🏠 Домашнее задание` только если в уроке есть задания (`homework_count > 0`) — это независимый вход, параллельный `▶ Начать урок`/`LessonRuntimeService` (см. 3.8): открытие через эту кнопку не двигает `current_section`, только сам runtime-переход (`▶ Далее`) продвигает прогресс. Список заданий (`STUDENT_LESSON_HOMEWORK_PREFIX`) показывает статус-иконку на каждое (⚪ не отвечено / ✅ верно / ❌ неверно / ⏳ на проверке). Открытие задания (`STUDENT_LESSON_HOMEWORK_TASK_PREFIX`): для `quiz` сразу показывает варианты inline-кнопками (`STUDENT_LESSON_HOMEWORK_QUIZ_ANSWER_PREFIX`); для `translation`/`free` включает pending-режим (`context.user_data["pending_homework_answer"]`, проверяется в начале `handle_student_lesson_message` до разбора остальных текстовых команд) и ждёт свободный текст следующим сообщением.

### 8.6.7 `lesson_grammar_items`

Ручной grammar-контент урока — информационная карточка, без AI и без проверки ответов.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | item id |
| `lesson_id` | INTEGER NOT NULL | lesson id |
| `position` | INTEGER NOT NULL DEFAULT 0 | порядок показа, назначается автоматически при создании (`Database.list_grammar_items()` + 1) |
| `title` | TEXT NOT NULL | заголовок темы |
| `explanation` | TEXT NOT NULL | объяснение |
| `example` | TEXT | опциональный пример |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

Teacher UI: `📝 Грамматика` внутри урока показывает список тем (`TEACHER_LESSON_GRAMMAR_PREFIX`), `➕ Добавить тему` → трёхшаговый текстовый ввод (заголовок → объяснение → опциональный пример, `'-'`/`'—'` чтобы пропустить пример), состояние `context.user_data["teacher_action"] = "teacher_create_grammar_item"` + `pending_grammar_item`. Просмотр темы (`TEACHER_LESSON_GRAMMAR_OPEN_PREFIX`) → `🗑 Удалить` с подтверждением, симметрично удалению homework-заданий.

Student UI: `📝 Грамматика`-этап (`STUDENT_LESSON_GRAMMAR_PREFIX`) показывает все темы урока одним экраном (заголовок, объяснение, пример), без интерактивной проверки — это read-only материал.

### 8.6.8 `lesson_exercise_items` и `lesson_exercise_answers`

Ручные упражнения урока — самопроверяемые (без AI), ответ сверяется точным совпадением после нормализации (та же нормализация, что и в `app/handlers/training.py::_normalize_answer`: lower-case, `ё`→`е`, схлопывание пробелов).

`lesson_exercise_items`:

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | item id |
| `lesson_id` | INTEGER NOT NULL | lesson id |
| `position` | INTEGER NOT NULL DEFAULT 0 | порядок показа |
| `prompt` | TEXT NOT NULL | текст упражнения |
| `expected_answer` | TEXT NOT NULL | правильный ответ |
| `hint` | TEXT | опциональная подсказка, показывается при неверном ответе |
| `created_at` | TEXT NOT NULL | UTC ISO string |
| `updated_at` | TEXT NOT NULL | UTC ISO string |

`lesson_exercise_answers` (append-only, как `homework_answers`; `Database.list_latest_exercise_answers(lesson_id, user_id)` берёт последнюю запись на упражнение):

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | answer id |
| `exercise_id` | INTEGER NOT NULL | `lesson_exercise_items.id` |
| `user_id` | INTEGER NOT NULL | answering user id |
| `answer` | TEXT NOT NULL | ответ ученика |
| `is_correct` | INTEGER NOT NULL | `0`/`1`, вычисляется сразу — ручной проверки нет |
| `created_at` | TEXT NOT NULL | UTC ISO string |

Teacher UI: `✏️ Упражнения` внутри урока — список/добавление (текст → правильный ответ → опциональная подсказка)/просмотр/удаление, симметрично `lesson_grammar_items`. Student UI: `✏️ Упражнения`-этап (`STUDENT_LESSON_EXERCISES_PREFIX`) показывает список упражнений со статус-иконкой (⚪/✅/❌); открытие упражнения ждёт свободный текст следующим сообщением (`context.user_data["pending_exercise_answer"]`) и сразу показывает результат — верно/неверно, при ошибке эталонный ответ и подсказку.

### `student_access`

Runtime allowlist учеников, которых teacher/admin добавляет из бота без изменения `.env`. Username хранится нормализованным: `trim`, без начального `@`, lower/casefold. Повторное добавление существующего username выставляет `is_active = 1` и обновляет `updated_at`.

| column | type | note |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | internal id |
| `username` | TEXT NOT NULL UNIQUE | normalized Telegram username |
| `display_name` | TEXT | optional label before first `/start` |
| `added_by_user_id` | INTEGER | admin/teacher `users.id`, if known |
| `is_active` | INTEGER NOT NULL DEFAULT 1 | active access flag |
| `created_at` | TEXT NOT NULL | UTC ISO timestamp |
| `updated_at` | TEXT NOT NULL | UTC ISO timestamp |

Связи на уровне приложения: `lessons.student_user_id` и `lessons.teacher_user_id` указывают на `users.id`; `lesson_words.lesson_id` указывает на `lessons.id`; `lesson_words.word_id` указывает на `words.id`; `homework_tasks.lesson_id` указывает на `lessons.id`; `homework_answers.task_id` указывает на `homework_tasks.id`; `homework_answers.user_id` указывает на `users.id`; `lesson_grammar_items.lesson_id` и `lesson_exercise_items.lesson_id` указывают на `lessons.id`; `lesson_exercise_answers.exercise_id` указывает на `lesson_exercise_items.id`; `lesson_exercise_answers.user_id` указывает на `users.id`.

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

## Teacher role

Минимальный teacher layer живёт поверх текущего main flow. `RoleResolver` в `app/auth/roles.py` определяет роли из настроек: admin, teacher и student. Teacher не получает admin-функций.

`app/handlers/teacher.py` обрабатывает только teacher menu:

- список учеников строится из student subset `allowed_usernames`, активных `student_access` и специального target `wp_bvv`; `wp_bvv` сохраняет роль `ADMIN`, но показывается teacher как `Вова (@wp_bvv)` для обучения/тестирования;
- прогресс ученика читается из существующих таблиц `words`, `daily_activity` и `word_progress`; если active `student_access` ещё не имеет строки в `users`, бот показывает сообщение «Ученик ещё не запускал бота…» и не открывает progress/impersonation;
- режим ученика сохраняет `impersonated_user_id` в `context.user_data`. `require_user()` возвращает выбранного student user для действий, но не меняет telegram_id teacher и не делает `upsert_user()` для ученика, поэтому дубли пользователей не создаются.

Остальной student game flow остаётся прежним: handlers слов, тренировок и игр продолжают работать с результатом `require_user()`.

## Admin role

Минимальный admin layer живёт поверх текущего main flow и использует `RoleResolver`. При `/start` admin остаётся в обычном student menu, но дополнительно видит кнопку `🛠 Админ`; lessons/homework не добавляются и game flow не меняется.

`app/handlers/admin.py` обрабатывает только admin-действия:

- `👨‍🎓 Войти как ученик` — выбор student target из student subset `allowed_usernames`, active `student_access` и специального `wp_bvv`; выбранный `users.id` сохраняется в `context.user_data["impersonated_user_id"]`, поэтому словарь/тренировки/игры выполняются как выбранный ученик без изменения telegram_id admin и без создания дублей; для выхода используется `↩️ Выйти из режима ученика`.
- `👩‍🏫 Войти как учитель` — включает `context.user_data["admin_teacher_view"]` и показывает teacher menu, чтобы admin мог проверить teacher UX без попадания в `TEACHER_USERNAMES`.
- `📊 Все пользователи` — выводит username, display_name, роль из `RoleResolver`, количество слов и текущий streak.
- `➕ Добавить ученика` — нормализует username, создаёт или реактивирует `student_access`, после чего ученик сможет пройти `/start`.
- `↩️ Моё меню` — возвращает admin в обычное student menu с кнопкой `🛠 Админ`.

`require_user()` разрешает impersonation для `ADMIN` и `TEACHER`, но возвращает существующего student user по `users.id`; `upsert_user()` продолжает применяться только к реальному Telegram user при входе, поэтому telegram_id admin не меняется и дубли users не создаются.


### 8.6.5 Lesson assignments

Lesson assignments are stored separately in `lesson_students`.

Lessons do not store `student_id`/`student_username` directly for the new assignment framework. The assignment layer keeps the current active target outside the lesson row, so teacher-side reassignment does not mutate lesson metadata.

Only one active assignment per lesson is supported now, enforced by a partial unique index on `lesson_students(lesson_id)` where `is_active = 1`, but historical inactive assignments are preserved for audit and future reporting. Assigning a different student deactivates the previous active row with `unassigned_at` and inserts a new active `ASSIGNED` row. Unassigning only deactivates the current row; it does not delete history.

Student menu shows `📚 Мои уроки` as an additional entry point on top of the full legacy menu (dictionary, cards, game, mistakes, exchange). Lessons do not replace or hide legacy navigation: legacy practice remains available regardless of lesson progress.

### 3.8 Lesson Runtime Framework

Lesson Runtime determines the next section independently of Telegram handlers, and drives real sequential progression through a lesson: `WORDS` → `GRAMMAR` → `EXERCISES` → `HOMEWORK` → `FINISHED`.

`app/lesson_runtime.py` owns `LessonSection` (the stage enum), `SECTION_ORDER` (the fixed sequence), and `LessonRuntimeService`:

- `get_next_section(lesson_id, student_username)` returns the student's persisted current stage (`lesson_students.current_section`, default `WORDS`) — this is a resume pointer, not a gate: opening any stage's content screen directly (e.g. the independent `🏠 Домашнее задание` entry, or re-opening `📖 Слова` to practice again) does not move the pointer.
- `advance_section(lesson_id, student_username)` moves the pointer past the current stage to the next one that actually has content, skipping `GRAMMAR`/`EXERCISES`/`HOMEWORK` when their item/task count is 0 (via `lesson_students`/`lessons` summary counts already computed by `Database.get_student_lesson()`). If nothing follows, it lands on `FINISHED` and stamps `lesson_students.completed_at`. This is the only thing that advances the pointer.

The student Lesson Overview handler asks `get_next_section` for where `▶ Начать урок` should land, and renders an intermediate "Следующий этап" screen (`_format_next_section`/`_start_section_keyboard`) with three actions: `▶ Открыть` (go into that stage's content screen), `▶ Далее` (`STUDENT_LESSON_NEXT_STAGE_PREFIX`, calls `advance_section` and re-renders this same intermediate screen for whatever section comes next — so repeated taps walk the whole sequence, skipping empty stages), and `⬅️ Урок` (back to overview without advancing). Handlers only render the returned stage and protect access through the existing lesson assignment lookup.

The Lesson Overview screen's progress list (`🟢`/`✅`/`⚪` per section) is derived purely from comparing `SECTION_ORDER` position against the current stage — no separate "completed" counters are stored.

`GRAMMAR` and `EXERCISES` content and their student-facing stage screens are documented in 8.6.5/8.6.6 above; `HOMEWORK`'s stage screen reuses the existing homework list (8.6.3/8.6.4) unchanged, whether reached through the runtime sequence or the independent `🏠 Домашнее задание` button.

#### Words stage practice (Phase 4, step 1)

The `📖 Слова` stage inside a lesson is no longer a placeholder: if the lesson has words, the student picks a mode —

- `🃏 Карточки` (`STUDENT_LESSON_WORDS_CARDS_PREFIX`) — same self-check flow as `🎯 Мои карточки` (weighted order, `Показать ответ` / `Помню` / `Не помню`), no study session recorded.
- `✍️ Ввод` (`STUDENT_LESSON_WORDS_TYPE_PREFIX`) — same typed-answer flow as `🎮 Игра на 10 слов` (AI check with fallback, `study_sessions` + `daily_activity` + XP recorded on finish).

Both reuse `app/handlers/training.py`'s existing card engine via `start_lesson_words_practice(update, context, words, typed=...)`, which seeds `context.user_data["training"]` and calls `send_current_card`. Unlike `🎮 Игра на 10 слов`, the practiced words are not a 10-word sample: **all** of the lesson's words are included (`Database.list_lesson_training_words(lesson_id, user_id)` — lesson words joined with the student's own `word_progress`, since lesson words are owned by the teacher, not the student). Progress is written under the practicing student's `user_id`, same `word_progress` table as free-form practice — a lesson word a student has already met through `🎯 Мои карточки`/`🎮 Игра` (e.g. copied into their own dictionary earlier) keeps a single shared progress row, it is not tracked per-lesson.

If a lesson has no words yet, the stage shows a message asking the student to wait for the teacher instead of the mode picker.

## Tutorial / Help / Notifications Foundation

Tutorial Framework provides reusable onboarding/help content.

TutorialStep may include feature_key for future feature-specific onboarding and announcements.

First-run onboarding is tracked in user_tutorials.

Product notification foundation is stored in product_notifications.

Lesson assignment may trigger best-effort student notifications without affecting assignment persistence.

Homework task creation triggers the same kind of best-effort notification: `NotificationService.notify_homework_assigned(bot, student_username, lesson, task)` (`app/notifications/notification_service.py`) fires only when the lesson already has an active student assignment at the moment the task is created; it never blocks or fails task creation — any exception from `bot.send_message` is caught and logged, mirroring `notify_lesson_assigned`.
