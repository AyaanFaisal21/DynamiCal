import { useState } from "react";
import { api, type CalEvent, type Suggestion } from "../api";
import { fmtRange, relativeDays } from "../lib/dates";
import type { Notify } from "../App";

interface Props {
  event: CalEvent;
  events: CalEvent[];
  onClose: () => void;
  onEdit: () => void;
  onChanged: (closed?: boolean) => void;
  notify: Notify;
}

const PREP_KINDS = new Set(["exam", "deadline", "interview"]);

export default function EventDrawer({ event: e, events, onClose, onEdit, onChanged, notify }: Props) {
  const [minutes, setMinutes] = useState(180);
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const start = new Date(e.start);
  const end = e.end ? new Date(e.end) : null;
  const titleFor = (id: number) => events.find((x) => x.id === id)?.title ?? `event #${id}`;

  const run = async (fn: () => Promise<unknown>, done: string, closed = false) => {
    setBusy(true);
    try {
      await fn();
      notify(done);
      onChanged(closed);
    } catch (err) {
      notify((err as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  const suggest = async () => {
    setBusy(true);
    try {
      const r = await api.suggest(e.id, minutes);
      setSuggestions(r.suggestions);
      if (!r.suggestions.length) notify("No free time found before this event inside your day bounds.");
    } catch (err) {
      notify((err as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  const addBlock = (s: Suggestion) =>
    run(
      async () => {
        await api.createEvent({ title: `Study: ${e.title}`, start: s.start, end: s.end, kind: "study", tentative: true, description: `Preparation for ${e.title}.` });
        setSuggestions((list) => list?.filter((x) => x !== s) ?? null);
      },
      "Study block added",
    );

  const remove = () => {
    const msg = e.source === "manual" || e.source === "chat" ? "Delete this block?" : "Remove this event? It will not come back from the same email.";
    if (!window.confirm(msg)) return;
    void run(() => api.deleteEvent(e.id), "Removed", true);
  };

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <aside className={"drawer k-" + e.kind}>
        <header>
          <h2>{e.title}</h2>
          <button className="btn ghost" onClick={onClose} aria-label="close">
            ✕
          </button>
        </header>
        <div className="body">
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="pill kind">{e.kind}</span>
            <span className={"pill " + e.status}>{e.status}</span>
            {e.tentative && <span className="pill">tentative</span>}
            <span className="pill">{e.source === "ics" ? "calendar file" : e.source}</span>
          </div>
          <dl className="kv">
            <dt>When</dt>
            <dd>
              {fmtRange(start, end, e.all_day)} <span className="muted">({relativeDays(start)})</span>
            </dd>
            {e.location && (
              <>
                <dt>Where</dt>
                <dd>{e.location}</dd>
              </>
            )}
            {e.conflicts.length > 0 && (
              <>
                <dt style={{ color: "var(--danger)" }}>Conflicts</dt>
                <dd>{e.conflicts.map(titleFor).join(", ")}</dd>
              </>
            )}
            {e.relationship && (
              <>
                <dt>Why it is here</dt>
                <dd>
                  {e.relationship}
                  {e.confidence !== null && <span className="muted">, confidence {Math.round(e.confidence * 100)}%</span>}
                </dd>
              </>
            )}
            {e.source_subject && (
              <>
                <dt>From email</dt>
                <dd>
                  {e.source_subject}
                  {e.source_from && <div className="muted small">{e.source_from}</div>}
                </dd>
              </>
            )}
          </dl>
          {e.description && <div className="quote">{e.description}</div>}
          {e.rationale && <div className="small muted">{e.rationale}</div>}

          {PREP_KINDS.has(e.kind) && e.status === "confirmed" && (
            <div className="card">
              <div className="title">Plan preparation time</div>
              <div className="actions">
                <select value={minutes} onChange={(ev) => setMinutes(Number(ev.target.value))}>
                  {[90, 180, 300, 480].map((m) => (
                    <option key={m} value={m}>
                      {m / 60} hours
                    </option>
                  ))}
                </select>
                <button className="btn" onClick={suggest} disabled={busy}>
                  Find free slots
                </button>
              </div>
              {suggestions && suggestions.length > 0 && (
                <div className="inline-list">
                  {suggestions.map((s) => (
                    <div key={s.start} className="suggestion">
                      <span>
                        {s.when} <span className="muted">({s.minutes} min)</span>
                      </span>
                      <button className="btn small primary" onClick={() => void addBlock(s)} disabled={busy}>
                        Add
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <footer>
          {e.status === "proposed" && (
            <>
              <button className="btn primary" disabled={busy} onClick={() => void run(() => api.accept(e.id), "Added to the calendar")}>
                Accept
              </button>
              <button className="btn" disabled={busy} onClick={() => void run(() => api.reject(e.id), "Rejected", true)}>
                Reject
              </button>
            </>
          )}
          <button className="btn" onClick={onEdit}>
            Edit
          </button>
          <button className="btn danger" onClick={remove} disabled={busy}>
            {e.source === "manual" || e.source === "chat" ? "Delete" : "Remove"}
          </button>
        </footer>
      </aside>
    </>
  );
}
