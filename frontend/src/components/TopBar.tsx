import { useEffect, useRef, useState } from "react";
import type { Alert, AppStatus } from "../api";
import { ago } from "../lib/dates";
import type { View } from "../App";

interface Props {
  view: View;
  onView: (v: View) => void;
  label: string;
  onMove: (dir: -1 | 0 | 1) => void;
  onSync: () => void;
  syncing: boolean;
  status: AppStatus | null;
  alerts: Alert[];
  onOpenEvent: (id: number) => void;
  sideOpen: boolean;
  onToggleSide: () => void;
  onNew: () => void;
}

export default function TopBar(p: Props) {
  const [alertsOpen, setAlertsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!alertsOpen) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setAlertsOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [alertsOpen]);

  const high = p.alerts.filter((a) => a.severity === "high").length;
  const model = p.status?.llm.enabled ? p.status.llm.model ?? p.status.llm.provider : "no model";
  const gmail = p.status ? (p.status.gmail.authorized ? `synced ${ago(p.status.gmail.last_sync)}` : "Gmail not connected") : "";

  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo" />
        DynamiCal
      </div>
      <div className="seg">
        <button className={p.view === "month" ? "on" : ""} onClick={() => p.onView("month")}>
          Month
        </button>
        <button className={p.view === "week" ? "on" : ""} onClick={() => p.onView("week")}>
          Week
        </button>
      </div>
      <button className="btn ghost" onClick={() => p.onMove(-1)} aria-label="previous">
        ‹
      </button>
      <button className="btn" onClick={() => p.onMove(0)}>
        Today
      </button>
      <button className="btn ghost" onClick={() => p.onMove(1)} aria-label="next">
        ›
      </button>
      <div className="range-label">{p.label}</div>
      <div className="spacer" />
      <div className="status-line">
        <span className="pill">{model}</span>
        <span>{gmail}</span>
      </div>
      <button className="btn" onClick={p.onSync} disabled={p.syncing || !p.status?.gmail.authorized} title={p.status?.gmail.authorized ? "Fetch new mail" : "Run `dynamical auth` first"}>
        {p.syncing ? "Syncing…" : "Sync"}
      </button>
      <button className="btn primary" onClick={p.onNew}>
        + Block
      </button>
      <div ref={menuRef} style={{ position: "relative" }}>
        <button className="btn bell" onClick={() => setAlertsOpen((v) => !v)} aria-label="alerts">
          Alerts
          {p.alerts.length > 0 && <span className={"badge" + (high ? "" : " medium")}>{p.alerts.length}</span>}
        </button>
        {alertsOpen && (
          <div className="menu">
            {p.alerts.length === 0 && <div className="item muted">Nothing needs attention.</div>}
            {p.alerts.map((a, i) => (
              <div
                key={i}
                className="item"
                onClick={() => {
                  if (a.event_id) p.onOpenEvent(a.event_id);
                  setAlertsOpen(false);
                }}
              >
                <span className={"sev " + a.severity} />
                <span>{a.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <button className="btn" onClick={p.onToggleSide} aria-label="toggle side panel">
        {p.sideOpen ? "Hide panel" : "Panel"}
      </button>
    </header>
  );
}
