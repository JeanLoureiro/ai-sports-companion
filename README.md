# Hybrid Athlete Coach

A Telegram coach that logs and plans BJJ, surf and gym training in one place and reasons across all three.
The full design lives in [the project plan](docs/Hybrid%20Athlete%20Coach%20%E2%80%94%20Project%20Plan.md).
How the system fits together is in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Local development

Requirements: uv, Docker, the Supabase CLI.

First time: `bash scripts/provision.sh` walks you through Supabase, both Telegram bots, the Anthropic key and the Vercel deploy, writing `backend/.env` as it goes.

```bash
supabase db start                 # local Postgres on 127.0.0.1:54422
cd backend
cp .env.example .env              # fill in the Telegram and Anthropic values
uv sync
uv run coach migrate
uv run coach add-athlete --name "Your Name" --chat-id <your Telegram chat id>
uv run coach poll                 # long polling; use a separate dev bot
```

Quality gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
