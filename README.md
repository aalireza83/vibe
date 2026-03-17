# Vibe Archive

Личный архив Telegram-переписок. Подключается к твоему аккаунту через MTProto API и сохраняет все входящие сообщения в PostgreSQL — текст, медиа, голосовые с транскрипцией. Сообщения остаются даже если собеседник их удалит.

## Возможности

- Архивирует личные переписки, боты, группы до N участников
- Все типы сообщений: текст, фото, видео, голосовые, кружки, стикеры, GIF, документы, опросы, геолокация, контакты
- Транскрипция голосовых и кружков через Telegram Premium API
- История редактирований сообщений
- Логирование удалённых сообщений
- Полнотекстовый поиск по-русски (PostgreSQL FTS)
- Веб-интерфейс с real-time обновлением (polling)
- Настройки через Django admin (лимит участников группы, скачивание файлов)

## Стек

- Python 3.13
- Django 5+ + PostgreSQL
- Telethon (Telegram MTProto)
- Bootstrap 5

## Установка

### 1. Получить Telegram API credentials

Зайди на [my.telegram.org](https://my.telegram.org) → API development tools → создай приложение. Запиши `api_id` и `api_hash`.

### 2. Клонировать и установить зависимости

```bash
git clone <repo>
cd vibe
uv sync
```

### 3. Создать базу данных

```bash
psql postgres
```

```sql
CREATE USER jesus WITH PASSWORD 'yourpassword';
CREATE DATABASE vibe OWNER jesus;
\q
```

### 4. Настроить окружение

```bash
cp .env.example .env
```

Заполнить `.env`:

```ini
SECRET_KEY=django-insecure-замени-на-случайную-строку
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=vibe
DB_USER=jesus
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432

TG_API_ID=12345678
TG_API_HASH=abcdef1234567890abcdef1234567890
TG_PHONE=+380XXXXXXXXX
```

> Файл сессии создаётся автоматически: `{номер без +}.session`

### 5. Применить миграции и создать суперпользователя

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

### 6. Запуск

Два терминала одновременно:

```bash
# Терминал 1 — веб-интерфейс
uv run python manage.py runserver

# Терминал 2 — Telegram listener
uv run python manage.py run_listener
```

При первом запуске listener запросит код из Telegram и пароль (если есть двухфакторная аутентификация). После этого сессия сохраняется и повторная авторизация не нужна.

Веб-интерфейс: [http://localhost:8000](http://localhost:8000)
Админка: [http://localhost:8000/admin](http://localhost:8000/admin)

## Настройки (админка)

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| Макс. участников в группе | 50 | Группы с большим числом игнорируются |
| Скачивать аудио | Нет | Скачивать музыкальные файлы |
| Скачивать документы | Нет | Скачивать файлы документов |
| Макс. размер файла (МБ) | 50 | Файлы больше не скачиваются |

## Структура медиафайлов

```
media/
└── {telegram_chat_id}/
    ├── photo/
    ├── video/
    ├── audio/
    ├── vnote/
    ├── sticker/
    ├── gif/
    └── document/
```
