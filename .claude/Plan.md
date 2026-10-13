# План: sqlite-repo-backuper

Docker-контейнер (аналог [docker-postgres-backup-local](https://github.com/prodrigestivill/docker-postgres-backup-local)),
который по расписанию делает консистентный снапшот SQLite, сжимает (опционально шифрует)
и отправляет в приватный GitHub-репозиторий с ротацией. Полностью автоматический:
сам создаёт репозиторий, сам делает бэкапы и чистит старые. Вся конфигурация — через env.

## Принятые решения

- **Только Docker-контейнер**, инжектится в проект как сервис в docker-compose, общий volume с БД.
- **Конфигурация только через env** (+ `*_FILE` для docker secrets).
- **Хранение — GitHub Release assets, один релиз на бэкап.**
  - Обычные коммиты не подходят: удалённые файлы остаются в истории, репо растёт бесконечно;
    лимит файла 100 МБ (предупреждение с 50 МБ).
  - Release asset: до 2 ГБ, удаление реально освобождает место.
  - Релиз на бэкап: ротация = `gh release delete --cleanup-tag`, нет лимита 1000 assets/релиз.
- **Работа с GitHub через `gh`** (subprocess), токен через `GH_TOKEN`.
- **Снапшот через `sqlite3.Connection.backup()`** (stdlib) — корректно с WAL и под нагрузкой,
  бинарник `sqlite3` не нужен. После — `PRAGMA integrity_check` на копии.
- Шифрование age — опционально, по умолчанию выключено.
- Несколько БД (`SQLITE_DB_PATHS`) — сразу.

## Автоматический сценарий при старте контейнера

1. Валидация env; при ошибке — понятное сообщение и exit.
2. `gh auth status`. Если `GITHUB_REPO` без owner — owner из токена (`gh api user`).
3. Репо не существует → `gh repo create --private --add-readme`
   (`--add-readme` нужен: релизу нужен тег, тегу — коммит).
   Репо существует, но пустой → создать initial commit через API.
4. Репо публичный → отказ с ошибкой (защита от утечки).
5. `BACKUP_ON_START=true` → бэкап сразу, далее по `SCHEDULE`.

## Пайплайн одного бэкапа

1. Снапшот каждой БД во временную директорию + `integrity_check`.
2. Сжатие (gzip по умолчанию, zstd опционально).
3. Шифрование age при заданном `AGE_RECIPIENT`.
4. Создание релиза с тегом `backup-<UTC timestamp>`, загрузка assets, sha256 в описании релиза.
5. Ротация по `KEEP_DAYS / KEEP_WEEKS / KEEP_MONTHS`
   (как в postgres-backup-local: последний бэкап каждого дня/недели/месяца).
6. Обновление healthcheck-маркера; при ошибке — webhook (если задан).

## Конфигурация (env)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `SQLITE_DB_PATHS` | — (обязательно) | Пути к БД через запятую |
| `GITHUB_REPO` | — (обязательно) | `owner/name` или `name` |
| `GH_TOKEN` / `GH_TOKEN_FILE` | — (обязательно) | Токен GitHub |
| `SCHEDULE` | `@daily` | cron-выражение или `@daily`/`@hourly`/... |
| `BACKUP_ON_START` | `false` | Бэкап сразу при старте |
| `BACKUP_KEEP_DAYS` | `7` | Дневных бэкапов хранить |
| `BACKUP_KEEP_WEEKS` | `4` | Недельных |
| `BACKUP_KEEP_MONTHS` | `6` | Месячных |
| `COMPRESSION` | `gzip` | `gzip` / `zstd` / `none` |
| `AGE_RECIPIENT` | — | Публичный ключ age; включает шифрование |
| `WEBHOOK_URL` | — | Вызывается при ошибке (например, healthchecks.io) |
| `TZ` | `UTC` | Таймзона для расписания |

**Токен:** надёжный вариант для автосоздания репо — classic PAT со scope `repo`.
Fine-grained возможен при доступе «All repositories» + `Administration: write` + `Contents: write` —
проверить на этапе 1 и задокументировать в README.

## Подключение к проекту

```yaml
services:
  app:
    volumes:
      - app-data:/data

  sqlite-backup:
    image: ghcr.io/<owner>/sqlite-repo-backuper:latest
    restart: unless-stopped
    volumes:
      - app-data:/data        # rw: для WAL нужен доступ к -shm
    environment:
      SQLITE_DB_PATHS: /data/app.db
      GITHUB_REPO: app-backups
      GH_TOKEN_FILE: /run/secrets/gh_token
      SCHEDULE: "0 3 * * *"
      BACKUP_KEEP_DAYS: 7
      BACKUP_KEEP_WEEKS: 4
      BACKUP_KEEP_MONTHS: 6
    secrets: [gh_token]

secrets:
  gh_token:
    file: ./gh_token.txt
```

## Команды (entrypoint)

```
run       # по умолчанию: демон с расписанием
backup    # один бэкап сейчас
prune     # только ротация
list      # список бэкапов
restore <tag|latest> -o /data/app.db   # скачать, расшифровать, распаковать, проверить
```

Восстановление: `docker compose run --rm sqlite-backup restore latest -o /data/app.db`

## Структура

```
src/sqlite_repo_backuper/
  config.py      # env -> dataclass, поддержка *_FILE
  snapshot.py    # backup API + integrity_check
  compress.py    # gzip/zstd, age
  github.py      # обёртка над gh: ensure_repo, create_release, list, delete, download
  retention.py   # чистая функция: список бэкапов -> что удалить
  scheduler.py   # цикл с croniter, SIGTERM
  health.py      # маркер последнего успешного бэкапа
  cli.py
tests/
Dockerfile                    # python:3.13-slim + gh + age, non-root, HEALTHCHECK
docker-compose.example.yml
.github/workflows/release.yml # сборка multi-arch и публикация в GHCR
```

Стек: uv, Python 3.13, ruff (line-length 100), pytest. Зависимости: `croniter`, `zstandard` (опц.).

## Этапы

1. **Ядро:** config (env, `*_FILE`), snapshot, gzip, `ensure_repo` (owner из токена, проверка
   приватности, initial commit), создание релиза с assets, команда `backup`.
   Проверка на реальном тестовом репо. Проверить fine-grained токен.
2. **Ротация, list, restore:** `retention.py` с юнит-тестами (основной риск багов).
3. **Демон:** `run` с croniter, `BACKUP_ON_START`, graceful shutdown, healthcheck.
4. **Docker:** Dockerfile, compose-пример, docker secrets, multi-arch, публикация в GHCR через Actions.
5. **Опции:** age, zstd, webhook при ошибках.

## Риски и тонкости

- **WAL + read-only mount:** `:ro` может ломать чтение WAL-базы (нужен `-shm`) — монтировать rw.
- **Лимит 2 ГБ на asset:** в MVP — явная ошибка; позже — split на части.
- **Атомарность:** при падении посреди загрузки не оставлять битый релиз — создавать релиз
  как draft, публиковать после загрузки всех assets; незавершённые draft'ы чистить при старте.
- **Rate limits GitHub API:** не проблема при расписании от раза в час.
- **Приватный ≠ зашифрованный:** для чувствительных данных рекомендовать `AGE_RECIPIENT`.
