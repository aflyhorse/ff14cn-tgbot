# FF14 Activity Telegram Bot

Telegram bot that scrapes seasonal events from the official FF14 China activity page and pushes updates to subscribers.

## Requirements

- Python 3.13 (virtualenv already configured at `.venv`)
- `TELEGRAM_BOT_TOKEN` environment variable
- SQLite by default, override with `DATABASE_URL` if needed

Dependencies are declared in `requirements.in` and compiled with `uv pip compile requirements.in -o requirements.txt`.

## Setup

```bash
cd /home/lunar/ff14cn-tgbot
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Running the bot

- Start bot (polling):

```bash
python main.py bot
```

- Cron: scrape and push new events

```bash
python main.py scan
```

- Cron: send reminders for events ending within 3 days that are still unconfirmed

```bash
python main.py countdown --within-days 3
```

## Telegram commands

- `/start` subscribe the current chat to updates
- `/list` send all current events
- Inline button "确认参加" under each event marks it as confirmed and suppresses countdown reminders

## Data model (SQLite)

- `subscribers` tracks chats
- `events` stores scraped activity metadata and parsed time range
- `event_deliveries` links events to subscribers, tracks sends/reminders/confirmations

## Notes

- Scraper searches for nodes containing "活动时间" on the source page and extracts nearby title/image/link heuristically.
- Only events with parsed `end_at` can be included in countdown reminders; others remain in `/list` results.
