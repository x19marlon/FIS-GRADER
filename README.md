# FIS Grader Telegram Bot

The Telegram bot provides quick access to repository activity stored in MongoDB Atlas.

It currently supports repository summaries, commits, student activity, analysis history, and Excel report generation.

## Setup

Create and activate the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install pymongo dnspython python-telegram-bot XlsxWriter
```

Set the required environment variables:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export MONGODB_URI="your_mongodb_uri"
export TELEGRAM_ALLOWED_USER_IDS="your_telegram_user_id"
```

## Run the Bot

From the project root:

```bash
python src/telegram/bot.py
```

Stop it with:

```bash
Ctrl+C
```

## Telegram Commands

```text
/whoami
/groups
/summary G1
/commits G1
/commits G1 5
/history G1
/student student@email.com
/excel G1
```

### Excel Reports

The `/excel` command generates and sends an `.xlsx` report containing:

* Overview and group metrics
* Author activity
* Repository commits
* Analysis history
* Activity charts

Example:

```text
/excel G1
```

The generated file is sent directly through Telegram.

## Current Flow

```text
GitHub Repositories
        ↓
GitHub Actions
        ↓
MongoDB Atlas
        ↓
Telegram Bot
        ↓
Reports / Queries / Excel
```
