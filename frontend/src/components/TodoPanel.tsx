import { useEffect, useState } from "react";
import { api, type AppStatus, type Digest } from "../api";
import { isoDate } from "../lib/dates";
import type { Notify } from "../App";

interface Props {
  anchor: Date;
  status: AppStatus | null;
  refreshKey: number;
  onOpenEvent: (id: number) => void;
  onChanged: () => void;
  notify: Notify;
}

export default function TodoPanel({ anchor, status, refreshKey, onOpenEvent, onChanged, notify }: Props) {
  const [scope, setScope] = useState<"day" | "week">("day");
  const [digest, setDigest] = useState<Digest | null>(null);
  const [narrating, setNarrating] = useState(false);
  const [newTask, setNewTask] = useState("");
  const date = isoDate(anchor);

  useEffect(() => {
    api
      .digest(scope, date, false)
      .then(setDigest)
      .catch((err: Error) => notify(err.message, true));
  }, [scope, date, refreshKey, notify]);

  const narrate = async () => {
    setNarrating(true);
    try {
      setDigest(await api.digest(scope, date, true));
    } catch (err) {
      notify((err as Error).message, true);
    } finally {
      setNarrating(false);
    }
  };

  const complete = async (id: number) => {
    try {
      await api.updateTask(id, { status: "done" });
      onChanged();
    } catch (err) {
      notify((err as Error).message, true);
    }
  };

  const addTask = async () => {
    if (!newTask.trim()) return;
    try {
      await api.createTask({ title: newTask.trim() });
      setNewTask("");
      onChanged();
    } catch (err) {
      notify((err as Error).message, true);
    }
  };

  const hours = (m: number) => (m >= 60 ? `${Math.round((m / 60) * 10) / 10} h` : `${m} min`);

  return (
    <div className="panel">
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <div className="seg">
          <button className={scope === "day" ? "on" : ""} onClick={() => setScope("day")}>
            Day
          </button>
          <button className={scope === "week" ? "on" : ""} onClick={() => setScope("week")}>
            Week
          </button>
        </div>
        <span className="small muted">{digest ? (scope === "day" ? digest.start : `${digest.start} to ${digest.end}`) : ""}</span>
        <div className="spacer" />
        {status?.llm.enabled && (
          <button className="btn small" onClick={() => void narrate()} disabled={narrating}>
            {narrating ? "Writing…" : "Briefing"}
          </button>
        )}
      </div>

      {digest?.narrative && <div className="quote">{digest.narrative}</div>}

      {digest?.suggestions.length ? (
        <div className="card" style={{ borderColor: "var(--warn)" }}>
          {digest.suggestions.map((s, i) => (
            <div key={i} className="small">
              {s}
            </div>
          ))}
        </div>
      ) : null}

      {digest?.days.map((d) => (
        <div key={d.date}>
          <h4 className="section-title">
            {d.label} <span style={{ fontWeight: 400 }}>· {hours(d.free_minutes)} free</span>
          </h4>
          {d.events.length === 0 && <div className="small muted">Nothing scheduled.</div>}
          {d.events.map((e) => (
            <div key={e.id} className={"task k-" + e.kind} style={{ cursor: "pointer" }} onClick={() => onOpenEvent(e.id)}>
              <span className="dot" style={{ background: "var(--k-event)", marginTop: 6 }} />
              <div>
                <div className="title">
                  {e.title}
                  {e.tentative && <span className="pill">tentative</span>}
                </div>
                <div className="small muted">
                  {e.when}
                  {e.location ? ` · ${e.location}` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}

      <h4 className="section-title">Tasks</h4>
      {digest && [...digest.tasks_overdue, ...digest.tasks_due, ...digest.tasks_undated].length === 0 && <div className="small muted">No open tasks in this period.</div>}
      {digest?.tasks_overdue.map((t) => (
        <div key={t.id} className="task">
          <input type="checkbox" onChange={() => void complete(t.id)} />
          <div>
            <div className="title">{t.title}</div>
            <div className="small" style={{ color: "var(--danger)" }}>
              overdue · {t.due}
            </div>
          </div>
        </div>
      ))}
      {digest?.tasks_due.map((t) => (
        <div key={t.id} className="task">
          <input type="checkbox" onChange={() => void complete(t.id)} />
          <div>
            <div className="title">
              {t.title} <span className="pill">{t.kind}</span>
            </div>
            <div className="small muted">due {t.due}</div>
          </div>
        </div>
      ))}
      {digest?.tasks_undated.map((t) => (
        <div key={t.id} className="task">
          <input type="checkbox" onChange={() => void complete(t.id)} />
          <div className="title">{t.title}</div>
        </div>
      ))}
      <div style={{ display: "flex", gap: 6 }}>
        <input
          className="btn"
          style={{ flex: 1, cursor: "text" }}
          placeholder="Add a task…"
          value={newTask}
          onChange={(e) => setNewTask(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void addTask();
          }}
        />
        <button className="btn" onClick={() => void addTask()} disabled={!newTask.trim()}>
          Add
        </button>
      </div>

      {digest && digest.coming_up.length > 0 && (
        <>
          <h4 className="section-title">Coming up</h4>
          {digest.coming_up.map((e) => (
            <div key={e.id} className={"task k-" + e.kind} style={{ cursor: "pointer" }} onClick={() => onOpenEvent(e.id)}>
              <span className="dot" style={{ background: "var(--k-event)", marginTop: 6 }} />
              <div>
                <div className="title">
                  {e.title} <span className="pill kind">{e.kind}</span>
                </div>
                <div className="small muted">
                  {e.when} · in {e.days_away} day{e.days_away === 1 ? "" : "s"}
                  {e.prep_minutes_planned ? ` · ${hours(e.prep_minutes_planned)} planned` : " · no prep planned"}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
