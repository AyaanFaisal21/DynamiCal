import { api, type CalEvent } from "../api";
import { fmtRange } from "../lib/dates";
import type { Notify } from "../App";

interface Props {
  proposals: CalEvent[];
  onOpenEvent: (id: number) => void;
  onChanged: () => void;
  notify: Notify;
}

export default function ReviewPanel({ proposals, onOpenEvent, onChanged, notify }: Props) {
  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      notify(done);
      onChanged();
    } catch (err) {
      notify((err as Error).message, true);
    }
  };

  if (!proposals.length) {
    return (
      <div className="panel">
        <div className="empty">
          Nothing to review.
          <div className="small" style={{ marginTop: 6 }}>
            Events the classifier was not sure about appear here. Registered and personal events go straight to the calendar.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      {proposals.map((e) => (
        <div key={e.id} className={"card k-" + e.kind}>
          <div className="title" style={{ cursor: "pointer" }} onClick={() => onOpenEvent(e.id)}>
            <span className="pill kind">{e.kind}</span>
            {e.title}
          </div>
          <div className="small">{fmtRange(new Date(e.start), e.end ? new Date(e.end) : null, e.all_day)}</div>
          {e.source_subject && (
            <div className="small muted">
              {e.source_from ? `${e.source_from}: ` : ""}
              {e.source_subject}
            </div>
          )}
          {e.rationale && <div className="small muted">{e.rationale}</div>}
          <div className="actions">
            <button className="btn small primary" onClick={() => void act(() => api.accept(e.id), "Added to the calendar")}>
              Accept
            </button>
            <button className="btn small" onClick={() => void act(() => api.reject(e.id), "Rejected")}>
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
