import { useEffect, useState } from "react";
import { api, type MailRecord } from "../api";
import { fmtDate } from "../lib/dates";
import type { Notify } from "../App";

interface Props {
  refreshKey: number;
  onOpenEvent: (id: number) => void;
  onChanged: () => void;
  notify: Notify;
}

const DECISION_LABEL: Record<string, string> = { skip: "skipped by rules", extract: "sent to model", ics: "calendar file" };

export default function InboxPanel({ refreshKey, onOpenEvent, onChanged, notify }: Props) {
  const [mail, setMail] = useState<MailRecord[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .mail(100)
      .then(setMail)
      .catch((err: Error) => notify(err.message, true));
  }, [refreshKey, notify]);

  const waiting = mail.filter((m) => m.status === "new" || m.status === "error").length;

  const retry = async () => {
    setBusy(true);
    try {
      const r = await api.retryPending();
      notify(r.summary);
      onChanged();
    } catch (err) {
      notify((err as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="small muted">
        Every fetched email and what the pipeline did with it.
        {waiting > 0 && (
          <>
            {" "}
            <button className="btn small" onClick={() => void retry()} disabled={busy}>
              Retry {waiting} waiting
            </button>
          </>
        )}
      </div>
      {mail.length === 0 && <div className="empty">No email yet. Press Sync, or run `dynamical ingest` on .eml files.</div>}
      {mail.map((m) => {
        const expanded = open === m.id;
        const rel = m.extraction?.relationship;
        return (
          <div key={m.id} className="card" style={{ cursor: "pointer" }} onClick={() => setOpen(expanded ? null : m.id)}>
            <div className="title" style={{ fontWeight: 500 }}>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: expanded ? "normal" : "nowrap" }}>{m.subject || "(no subject)"}</span>
            </div>
            <div className="small muted">
              {m.from_name || m.from_email} · {fmtDate(new Date(m.date))}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <span className={"pill " + m.status}>{m.status}</span>
              {m.triage_decision && (
                <span className="pill">
                  {DECISION_LABEL[m.triage_decision] ?? m.triage_decision}
                  {m.triage_score !== null ? ` (${m.triage_score > 0 ? "+" : ""}${m.triage_score})` : ""}
                </span>
              )}
              {rel && <span className="pill">{rel}</span>}
              {m.event_ids.length > 0 && (
                <span className="pill" style={{ color: "var(--ok)" }}>
                  {m.event_ids.length} event{m.event_ids.length > 1 ? "s" : ""}
                </span>
              )}
            </div>
            {expanded && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                {m.extraction?.summary && <div className="small">{m.extraction.summary}</div>}
                {m.extraction?.rationale && <div className="small muted">{m.extraction.rationale}</div>}
                {m.triage_reasons.length > 0 && (
                  <ul className="reasons">
                    {m.triage_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
                {m.error && <div className="error">{m.error}</div>}
                {m.event_ids.length > 0 && (
                  <div className="actions">
                    {m.event_ids.map((id) => (
                      <button key={id} className="btn small" onClick={() => onOpenEvent(id)}>
                        Open event #{id}
                      </button>
                    ))}
                  </div>
                )}
                <div className="quote small" style={{ maxHeight: 160, overflow: "auto" }}>
                  {m.snippet}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
