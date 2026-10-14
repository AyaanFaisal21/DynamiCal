import { useState } from "react";
import type { CalEvent } from "../api";
import { isoDate, toInput } from "../lib/dates";

export interface FormValues {
  title: string;
  kind: string;
  all_day: boolean;
  start: string; // ISO
  end: string | null; // ISO
  tentative: boolean;
  location: string | null;
  description: string | null;
}

interface Props {
  event?: CalEvent;
  defaults?: Partial<FormValues>;
  onCancel: () => void;
  onSave: (values: FormValues, id?: number) => Promise<void>;
}

export const KINDS = ["study", "practice", "event", "class", "exam", "deadline", "meeting", "appointment", "social", "interview", "other"];

export default function EventForm({ event, defaults, onCancel, onSave }: Props) {
  const base: FormValues = {
    title: event?.title ?? defaults?.title ?? "",
    kind: event?.kind ?? defaults?.kind ?? "study",
    all_day: event?.all_day ?? defaults?.all_day ?? false,
    start: event?.start ?? defaults?.start ?? new Date().toISOString(),
    end: event?.end ?? defaults?.end ?? null,
    tentative: event?.tentative ?? defaults?.tentative ?? true,
    location: event?.location ?? defaults?.location ?? null,
    description: event?.description ?? defaults?.description ?? null,
  };
  const startDate = new Date(base.start);
  const endDate = base.end ? new Date(base.end) : new Date(startDate.getTime() + 60 * 60_000);

  const [title, setTitle] = useState(base.title);
  const [kind, setKind] = useState(base.kind);
  const [allDay, setAllDay] = useState(base.all_day);
  const [start, setStart] = useState(toInput(startDate));
  const [end, setEnd] = useState(toInput(endDate));
  const [day, setDay] = useState(isoDate(startDate));
  const [tentative, setTentative] = useState(base.tentative);
  const [location, setLocation] = useState(base.location ?? "");
  const [description, setDescription] = useState(base.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!title.trim()) return setError("A title is needed.");
    let startIso: string;
    let endIso: string | null;
    if (allDay) {
      const d = new Date(day + "T00:00");
      startIso = d.toISOString();
      endIso = new Date(d.getTime() + 24 * 60 * 60_000).toISOString();
    } else {
      const s = new Date(start);
      const en = new Date(end);
      if (Number.isNaN(s.getTime())) return setError("Start is not a valid time.");
      if (Number.isNaN(en.getTime()) || en <= s) return setError("End must be after start.");
      startIso = s.toISOString();
      endIso = en.toISOString();
    }
    setBusy(true);
    try {
      await onSave(
        { title: title.trim(), kind, all_day: allDay, start: startIso, end: endIso, tentative, location: location.trim() || null, description: description.trim() || null },
        event?.id,
      );
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <>
      <div className="backdrop" onClick={onCancel} />
      <form className="modal" onSubmit={submit}>
        <header>
          <h2>{event ? "Edit event" : "New block"}</h2>
          <button type="button" className="btn ghost" onClick={onCancel} aria-label="close">
            ✕
          </button>
        </header>
        <div className="body form">
          <label>
            Title
            <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Study for CS 211 midterm" />
          </label>
          <div className="row">
            <label>
              Kind
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            <label className="check" style={{ alignSelf: "end", paddingBottom: 8 }}>
              <input type="checkbox" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} /> All day
            </label>
          </div>
          {allDay ? (
            <label>
              Day
              <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
            </label>
          ) : (
            <div className="row">
              <label>
                Start
                <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
              </label>
              <label>
                End
                <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
              </label>
            </div>
          )}
          <label className="check">
            <input type="checkbox" checked={tentative} onChange={(e) => setTentative(e.target.checked)} /> Tentative. Shown hatched, can move if something firm comes up.
          </label>
          <label>
            Location
            <input value={location} onChange={(e) => setLocation(e.target.value)} />
          </label>
          <label>
            Notes
            <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          {error && <div className="error">{error}</div>}
        </div>
        <footer>
          <button type="submit" className="btn primary" disabled={busy}>
            {event ? "Save" : "Add to calendar"}
          </button>
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        </footer>
      </form>
    </>
  );
}
