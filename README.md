# DynamiCal

A personal calendar that fills itself from your email.

DynamiCal reads your Gmail inbox, works out which emails describe real commitments, and puts those on a calendar. It ignores events that are only advertised to you. A chat panel answers questions about your days and finds free time for study. The work is done by ordinary code. A language model is used only where judgement is needed.

## What it does

| Feature | How |
| --- | --- |
| Pull emails from Gmail | Gmail API, read-only OAuth scope, incremental sync |
| Decide what is worth a look | Rule-based triage: Gmail categories, list headers, sender trust, keywords |
| Read calendar attachments | Direct `.ics` parsing. No model needed |
| Classify the rest | Gemini Flash or a local model returns one strict JSON object per email |
| Add or propose or drop | A policy with tunable thresholds. Registered and personal items are added. Org announcements are proposed. Marketing is dropped |
| Avoid duplicates | Upsert by calendar UID, by title plus date, and by email thread |
| Flag conflicts | Overlap check across confirmed events and tentative blocks |
| Study and practice blocks | Tentative blocks that the free-time finder can place for you |
| Chat | Ask "what do I have on Thursday" or "when can I study for the midterm". The model calls calendar tools, then answers |
| To-do digests | Daily and weekly lists built from events, deadlines, and extracted tasks |

## Model options

Set `LLM_PROVIDER` in `.env`.

| Provider | When to use | Setup |
| --- | --- | --- |
| `gemini` | Default. Fast and cheap | Put a key in `GEMINI_API_KEY`. Default model is `gemini-3.8-flash` |
| `local` | Keep email on your machine | Run Ollama, llama.cpp `llama-server`, or `mlx_lm.server`. Set `LOCAL_LLM_BASE_URL` and `LOCAL_LLM_MODEL` |
| `none` | No model at all | Calendar attachments still sync. Other emails wait |

On a 16 GB Mac, a 7B or 8B instruct model in 4-bit quantization is the practical size for the local option. The local backend asks the server for JSON output and runs tool calls through a JSON planner, so the model does not need native tool calling.

## Setup

1. Python 3.11 or newer, and Node 20 or newer.
2. Create the environment and install:

   ```bash
   python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
   ```

3. Copy `.env.example` to `.env`. Fill in `USER_EMAIL`, `TRUSTED_DOMAINS`, and the model settings.
4. Gmail access:
   1. In Google Cloud, create a project and enable the Gmail API.
   2. Create an OAuth client of type Desktop app. Download the JSON.
   3. Save it as `secrets/credentials.json`.
   4. Run `.venv/bin/dynamical auth`. A browser window asks you to sign in. The token is saved to `secrets/token.json`.
5. First sync: `.venv/bin/dynamical sync`.
6. Run the server: `.venv/bin/dynamical serve`, then open http://127.0.0.1:8000.

Nothing in `secrets/` or `data/` is committed.

## Commands

| Command | Purpose |
| --- | --- |
| `dynamical auth` | Sign in to Gmail once |
| `dynamical sync [--days N] [--max N]` | Fetch new mail and update the calendar |
| `dynamical ingest FILE...` | Run the pipeline on `.eml` files. Good for testing without Gmail |
| `dynamical serve` | Start the API and the web app |
| `dynamical status` | Show counts and the last sync time |

## Layout

```
backend/dynamical/
  config.py        settings from .env
  db.py models.py  SQLite through SQLAlchemy
  gmail/           OAuth, API client, RFC 822 parsing
  ingest/          triage -> ics or extract -> policy -> upsert
  llm/             gemini and local backends behind one interface
  calendar/        conflicts and free time
  chat/            tools and the bounded tool-calling loop
  todo/            daily and weekly digests
  api/             FastAPI routes
backend/tests/     pytest, with synthetic .eml fixtures
frontend/          React app: month and week views, review queue, chat panel
```

## Tests

```bash
.venv/bin/pytest
```

The tests use synthetic emails in `backend/tests/fixtures/emails`. No network and no model are needed.
