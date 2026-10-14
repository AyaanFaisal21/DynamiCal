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
5. Build the web app once: `cd frontend && pnpm install && pnpm build`.
6. First sync: `.venv/bin/dynamical sync`.
7. Run the server: `.venv/bin/dynamical serve`, then open http://127.0.0.1:8000.

Nothing in `secrets/` or `data/` is committed.

### Try it without Gmail or a model

```bash
.venv/bin/dynamical demo
DYNAMICAL_DB=./data/demo.db .venv/bin/dynamical serve
```

The demo loads nine synthetic emails with canned model output: a ticket
confirmation, a calendar invite, a friend's dinner plan, a course exam notice,
a Canvas deadline, a health appointment, a department announcement that
lands in the review queue, and two bulk emails that the rules drop.

## Commands

| Command | Purpose |
| --- | --- |
| `dynamical auth` | Sign in to Gmail once |
| `dynamical sync [--days N] [--max N]` | Fetch new mail and update the calendar |
| `dynamical ingest FILE...` | Run the pipeline on `.eml` files. Good for testing without Gmail |
| `dynamical serve` | Start the API and the web app |
| `dynamical status` | Show counts and the last sync time |
| `dynamical demo` | Load the sample emails into `data/demo.db` |

## How an email becomes an event

1. **Triage** (`ingest/triage.py`). Rules score each email. Gmail's own
   category is the strongest signal. List headers, no-reply senders, and
   marketing words count against. Trusted domains, direct addressing, and
   commitment words such as "your ticket" or "due" count for. A score of -4 or
   lower is dropped without a model call. A calendar attachment skips the
   model entirely.
2. **Extraction** (`ingest/extract.py`). The model returns one JSON object: a
   relationship label (registered, personal, invited, course, informational,
   promotional, none), the events with ISO times, and any tasks.
3. **Policy** (`ingest/policy.py`). Registered, personal, invited, and course
   items are added when confidence is at or above `AUTO_ADD_THRESHOLD`, and
   proposed between `PROPOSE_THRESHOLD` and that. Informational items are
   always proposed, never added. Promotional items are dropped. "You're
   invited" sent to a list is informational, not invited.
4. **Upsert** (`ingest/upsert.py`). A calendar UID, a title-plus-date
   fingerprint, or the email thread identifies an existing event. Updates
   change times in place. Cancellations mark the event cancelled. A rejected
   event never comes back.

The Inbox tab in the web app shows this trail for every email: the triage
score and reasons, the relationship, and the events that came out.

## Chat

The side panel sends your question to the model with a set of tools: events
in a range, upcoming exams and deadlines, free time on a day, open tasks,
pending proposals, the source email of an event, and study-block suggestions.
The model calls tools, the code answers them, and the model writes the reply.
Tool rounds are capped at six. Creating a block or task from chat only
happens when you ask for it.

With `LLM_PROVIDER=none` the chat can still list a day's events.

## Development

```bash
.venv/bin/pytest                    # backend tests, no network
cd frontend && pnpm dev             # web app on :5173, proxies /api to :8000
.venv/bin/dynamical serve --reload  # API with auto reload
```

`ENGINEERING_LOG.md` records the problems met while building this, including
the small ones.

## Not done yet

- Two-way Google Calendar sync. Events already carry an `external_id` field for it.
- Desktop or push notifications. The `/api/alerts` endpoint has the data.
- Recurring events from calendar files. Only the first instance is read.
- Preferred study hours. Suggested blocks start at the day start hour.

## Layout

```
backend/dynamical/
  config.py        settings from .env
  demo.py          sample emails and canned model output
  db.py models.py  SQLite through SQLAlchemy
  gmail/           OAuth, API client, RFC 822 parsing
  ingest/          triage -> ics or extract -> policy -> upsert
  llm/             gemini and local backends behind one interface
  calendar/        conflicts and free time
  chat/            tools and the bounded tool-calling loop
  todo/            daily and weekly digests
  api/             FastAPI routes
backend/tests/     pytest, with synthetic .eml fixtures
frontend/          React app: month and week views, event drawer, side panel
```

## Tests

```bash
.venv/bin/pytest
```

The tests use synthetic emails in `backend/tests/fixtures/emails`. No network and no model are needed.
