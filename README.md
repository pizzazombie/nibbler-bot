# Nibbler bot

Your tiny Telegram calorie goblin.

Send a food photo or describe a meal in text. Nibbler stares at it with OpenAI vision, or reads your snack confession, then guesses what you ate, how much of it, and how many calories probably landed in your mortal body.

Then it waits politely:

- `✅ Save meal` if the estimate is correct
- `❌ Ignore` if it is nonsense
- send a correction like `It was Coke Zero and one glass of champagne` to re-run the same photo

Only confirmed meals count.
<img width="823" height="639" alt="image" src="https://github.com/user-attachments/assets/36cb777a-f3e0-40b3-8158-780279457b28" />

## What It Does

- analyzes exactly one meal photo at a time
- accepts text-only meal descriptions
- accepts a caption with extra context
- asks OpenAI to include approximate grams for solid food and milliliters for drinks
- lets the user correct the estimate in plain English
- stores daily calories, protein, fat, carbs, and fiber per user
- asks for name, daily calorie goal, and nutrition goal during onboarding
- protects access with a password and monthly-reset attempt limits
- lets the user change name, calorie limit, nutrient limits, and delete today's meals from `⚙️ Settings`
- sends a Monday morning weekly recap with a generated chart
- sends a monthly trend summary on the first day of the next month
- tracks OpenAI usage cost, generation counts, and user activity in SQLite for future admin stats
- limits each user to `100` generations per day by default
- supports admin-only monitoring commands for the owner

## Stack

- Python 3.11+
- `python-telegram-bot`
- OpenAI Responses API
- SQLite via `aiosqlite`
- Pillow for lightweight chart rendering
- Docker + GitHub Actions deploy to a small VPS

## Why This Setup

The bot is designed for a very small server:

- single process
- SQLite database in a Docker volume
- no Redis
- no external database
- no scheduled CI test runs burning GitHub minutes

Persistent data lives in `/data/nibbler-bot.db` inside the container and is backed by the named Docker volume `nibbler_bot_data`.

## OpenAI Notes

The default model is `gpt-5.4-mini`, because it supports image input and structured outputs while staying relatively cheap.

You can switch models later with GitHub variables:

- `OPENAI_MODEL`
- `OPENAI_REASONING_EFFORT`
- `OPENAI_PRICE_INPUT_PER_1M_USD`
- `OPENAI_PRICE_CACHED_INPUT_PER_1M_USD`
- `OPENAI_PRICE_OUTPUT_PER_1M_USD`

That way, usage-cost tracking still stays accurate after a model switch.

Useful docs:

- [OpenAI model comparison](https://developers.openai.com/api/docs/models/compare)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

## Local Development

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create `.env.local` from `.env.example`, export the variables, then run:

```bash
python -m nibbler_bot
```

For Docker smoke tests:

```bash
docker compose --env-file .env.local up --build
```

## Tests

Tests are meant to run locally:

```bash
pytest
```

The deploy workflow does not run tests on GitHub Actions.

## Required GitHub Secrets

- `VPS_SSH_KEY`
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `ACCESS_PASSWORD`

Example password value if you want the original setup:

```text
health
```

## Recommended GitHub Variables

- `VPS_HOST`
- `VPS_USER`
- `VPS_PORT`
- `TIMEZONE`
- `DOCKER_NETWORK_MODE`
- `OPENAI_MODEL`
- `OPENAI_REASONING_EFFORT`
- `OPENAI_MAX_OUTPUT_TOKENS`
- `OPENAI_REQUEST_TIMEOUT_SECONDS`
- `OPENAI_PRICE_INPUT_PER_1M_USD`
- `OPENAI_PRICE_CACHED_INPUT_PER_1M_USD`
- `OPENAI_PRICE_OUTPUT_PER_1M_USD`
- `DEFAULT_DAILY_CALORIE_LIMIT`
- `DAILY_GENERATION_LIMIT`
- `WEEKLY_SUMMARY_HOUR`
- `WEEKLY_SUMMARY_MINUTE`
- `MONTHLY_SUMMARY_HOUR`
- `MONTHLY_SUMMARY_MINUTE`
- `ADMIN_CHAT_IDS`

## Admin Monitoring

If `ADMIN_CHAT_IDS` contains your Telegram private `chat_id`, only that chat gets the extra bot commands:

- `/health`
- `/server`
- `/containers`

These commands are scoped to the admin chat and are not shown to regular users.

## Deploy

Push to `main`, and GitHub Actions will:

1. archive the repository
2. upload it to the VPS
3. write `.env.production` from GitHub secrets and variables
4. rebuild the Docker image
5. restart the service with persistent volume storage

## Bot Behavior Summary

### First Run

1. user starts the bot
2. bot asks for password
3. bot asks for name
4. bot asks for daily calorie goal
5. bot is ready

### Meal Flow

1. user sends one photo, optionally with text, or just describes the meal
2. bot estimates items, calories, protein, fat, carbs, and fiber
3. user either saves it, ignores it, or sends a correction
4. only saved meals affect the daily total

### Important Edge Cases

- if the user sends a new photo before confirming the old one, the old pending estimate is replaced
- if the user sends a text correction without pressing any button, the same photo is analyzed again with that correction
- if the user sends an album, the bot asks for one photo at a time

## Project Layout

```text
src/nibbler_bot/
  bot.py
  charts.py
  config.py
  formatting.py
  meal_analyzer.py
  models.py
  storage.py
tests/
.github/workflows/deploy.yml
docker-compose.yml
Dockerfile
```

## Public Repo Safety

- no secrets are committed
- runtime secrets come from GitHub Secrets
- the password is read from `ACCESS_PASSWORD`
- the SQLite database lives only on the server volume

Nibbler is small, hungry, and reasonably disciplined.
