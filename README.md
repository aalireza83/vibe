# Vibe Archive

Personal Telegram archive. Connects to your account via MTProto API and saves all incoming messages to PostgreSQL — text, media, voice with transcription. Messages are preserved even if the other party deletes them.

## Features

- Archives private chats, bots, and groups up to N members
- All message types: text, photos, videos, voice messages, video notes, stickers, GIFs, documents, polls, locations, contacts
- Voice and video note transcription via Telegram Premium API
- Message edit history
- Deleted message logging
- Full-text search (PostgreSQL FTS)
- Web UI with real-time updates (polling)
- Media gallery per chat (photos, videos, GIFs)
- Bookmarks
- Message filters: by type, deleted, edited, bookmarked
- Export chat to JSON or CSV
- Reply quotes
- Dark / light theme
- Settings via Django admin (group member limit, file downloads)

## Stack

- Python 3.13
- Django 5+ + PostgreSQL
- Telethon (Telegram MTProto)
- Bootstrap 5

## Installation

### 1. Get Telegram API credentials

Go to [my.telegram.org](https://my.telegram.org) → API development tools → create an app. Save `api_id` and `api_hash`.

### 2. Clone and install dependencies

```bash
git clone https://github.com/vladrunk/vibe.git
cd vibe
uv sync
```

### 3. Create database

```bash
psql postgres
```

```sql
CREATE USER vibe WITH PASSWORD 'yourpassword';
CREATE DATABASE vibe OWNER vibe;
\q
```

### 4. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

```ini
SECRET_KEY=django-insecure-replace-with-random-string
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=vibe
DB_USER=vibe
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432

TG_API_ID=12345678
TG_API_HASH=abcdef1234567890abcdef1234567890
TG_PHONE=+1XXXXXXXXXX
```

> Session file is created automatically: `{phone_without_plus}.session`

### 5. Apply migrations and create superuser

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

### 6. Run

Two terminals simultaneously:

```bash
# Terminal 1 — web interface
uv run python manage.py runserver

# Terminal 2 — Telegram listener
uv run python manage.py run_listener
```

On first run the listener will ask for a Telegram confirmation code and password (if two-factor authentication is enabled). After that the session is saved and re-authorization is not needed.

Web UI: [http://localhost:8000](http://localhost:8000)
Admin: [http://localhost:8000/admin](http://localhost:8000/admin)

## Sync history

To backfill messages without running the listener:

```bash
# Last 7 days (default)
uv run python manage.py sync_history

# Last 30 days
uv run python manage.py sync_history --days 30

# Specific chat
uv run python manage.py sync_history --chat 123456789
```

## Admin settings

| Setting | Default | Description |
|---------|---------|-------------|
| Max group members | 50 | Groups above this limit are ignored |
| Download audio | No | Download music files |
| Download documents | No | Download document files |
| Max file size (MB) | 50 | Files larger than this are skipped |

## Media structure

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
