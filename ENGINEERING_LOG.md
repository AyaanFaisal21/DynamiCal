# Engineering log

Problems met while building DynamiCal, including the small ones. Each entry says
what went wrong, why it would have stayed hidden, and how it was fixed.
Newest entries go at the bottom of each phase.

## Phase 1: backend

**SQLite drops time zones.** SQLAlchemy's `DateTime` on SQLite returns naive
values. A 3 PM EDT event stored as 19:00 UTC would come back as a naive 19:00
and render as 7 PM. Nothing crashes, so this stays hidden until a user compares
the calendar with the email. Fix: a `UTCDateTime` column type that requires
aware input and re-attaches UTC on read. A test writes an EDT value and reads
back an equal aware UTC value.

**Python 3.11 venv could not bootstrap pip.** `python3.11 -m venv` failed inside
`ensurepip` on this machine. Used the python.org 3.13 build instead. The
project requires 3.11 or newer, so nothing else changed.

**The Gemini docs moved to a new API mid-project.** Google's current docs lead
with an Interactions API (`client.interactions.create`) and call
`generate_content` legacy but fully supported. The installed SDK exposes the
new call with untyped `request: Any`, so the shapes could not be checked
locally. Chose `generate_content`, whose config fields the SDK does expose
(`system_instruction`, `tools`, `response_schema`, `thinking_config`). Migration
later is a one-file change in `llm/gemini.py`.

**Blind broadcasts looked like personal mail.** The fixture with
`To: undisclosed-recipients:;` parsed to an empty recipient list, so neither the
"undisclosed" check nor the "user not a recipient" check fired, and an org
blast scored high enough to reach the model. Fix: an empty recipient list is
itself a negative signal. The triage test table caught it.

**A reminder email renamed the event.** "Reminder: Hackathon Kickoff" matched
the stored "Hackathon Kickoff" by fingerprint, then the title update rule
replaced the title with the prefixed one. Fix: only update the title when the
normalised titles differ.

**Thread matching merged an exam with its review session.** Both events came
from one course email in one thread. The title rule ("most of the shorter
title's words appear in the longer one") matched "CS 211 Midterm 2" against
"CS 211 Midterm 2 review session" and the review session overwrote the exam.
Idempotency tests passed because the second run was consistent with the first;
only the count assertion (6 events, not 7) exposed it. Fixes: events extracted
from the same email never match each other, the strict rule now needs a
Jaccard overlap of 0.75, and the loose containment rule only applies when the
model says the email is an update.

**Single-event responses never showed conflicts.** The serializer computed
conflicts among the rows it was given. For `GET /api/events/{id}` that was one
row, so `conflicts` was always empty while the list endpoint showed them. Fix:
load the event's neighbours before serializing one event.

**Test assumption about the end of the day.** A free-time test assumed the exam
was the last thing on the day, but one free hour followed it before the day end
at 11 PM. The code was right. The test now checks that no slot overlaps the
exam.

## Phase 2: frontend

**Month grid showed three columns.** `grid-template-columns: repeat(7, 1fr)`
looked right, but `1fr` means `minmax(auto, 1fr)`, and the chips inside the
cells use `white-space: nowrap`. The auto minimum became the widest chip, the
seven columns overflowed the container, and `overflow: hidden` clipped
Thursday to Sunday without any error. Fix: `repeat(7, minmax(0, 1fr))` plus
`min-width: 0` on the cells. The week view got the same treatment before it
could fail the same way.

**A flex column split a sentence.** The "no model configured" note was a
`.card`, which is a flex column, so each inline `<code>` became its own flex
item on its own line. Fix: wrap the text in a paragraph. Rule for this
codebase: text goes inside a block element, never directly inside a flex
container.

**The preview launcher cannot read the project folder.** The desktop app's
dev-server launcher runs in a sandbox that got "Operation not permitted" on
`.venv/pyvenv.cfg` under Documents. The server starts fine from a normal
shell. Workaround: start it from the shell and open the browser pane at the
URL.

**Study blocks land at 8 AM.** The suggestion rule takes the largest free slot
of each day and starts the block at the slot's start, which is the day start
hour. Correct by the rule, but not when a student would study. Left as is and
noted as the first thing to tune: a preferred-hours setting.
