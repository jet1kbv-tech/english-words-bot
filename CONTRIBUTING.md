# Development Rules

## One feature = one PR

Каждая задача должна быть отдельным PR.

Не объединять несколько функций в одном PR.

## Keep PRs small

Изменять только необходимые файлы.

Не делать рефакторинг, если задача его не требует.

## Preserve existing behavior

Не менять существующее поведение без явной просьбы.

Если задача про lessons — не менять game flow.

Если задача про teacher — не менять student flow.

## Database changes

Только additive changes.

Можно добавлять таблицы и поля через CREATE TABLE IF NOT EXISTS / ALTER TABLE.

Нельзя удалять таблицы, поля или менять существующие данные без отдельной миграционной задачи.

## Menus

Не менять существующие кнопки без явной задачи.

Если добавляется новая кнопка, проверить, что старые кнопки продолжают работать.

## AI features

Все AI-функции должны иметь fallback без AI.

Не отправлять в AI лишние персональные данные.

## Environment

Не трогать .env.

Новые переменные добавлять только в .env.example и README.

## Tests

Перед PR выполнить:

python -m compileall main.py app scripts
python -m pytest

## Merge requirements

PR можно мержить только после зелёного CI (`.github/workflows/ci.yml`).

Обязательные проверки:

- `python -m compileall main.py app scripts`;
- `python -m pytest`;
- отсутствие неразрешённых merge-маркеров (`<<<<<<<`, `=======`, `>>>>>>>`) вне Markdown.

После merge в `main` deploy (`.github/workflows/deploy.yml`) запускается автоматически, но только после повторного прохождения тех же проверок в этом workflow. Если проверки падают, deploy не выполняется и systemd-сервис на сервере не перезапускается.

## Conflict prevention

Перед началом задачи работать от актуального main.

Если PR конфликтует с main, лучше создать новый clean PR от актуального main, чем чинить старую конфликтную ветку.
