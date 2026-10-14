import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Alert, type AppStatus, type CalEvent } from "./api";
import { addDays, addMonths, fmtDate, monthGrid, startOfWeek } from "./lib/dates";
import TopBar from "./components/TopBar";
import MonthView from "./components/MonthView";
import WeekView from "./components/WeekView";
import EventDrawer from "./components/EventDrawer";
import EventForm, { type FormValues } from "./components/EventForm";
import SidePanel, { type Tab } from "./components/SidePanel";

export type View = "month" | "week";
export type Notify = (text: string, error?: boolean) => void;

export default function App() {
  const [view, setView] = useState<View>("week");
  const [anchor, setAnchor] = useState(() => new Date());
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [selected, setSelected] = useState<CalEvent | null>(null);
  const [editing, setEditing] = useState<{ event?: CalEvent; defaults?: Partial<FormValues> } | null>(null);
  const [sideOpen, setSideOpen] = useState(true);
  const [tab, setTab] = useState<Tab>("chat");
  const [tick, setTick] = useState(0);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(null);
  const [syncing, setSyncing] = useState(false);
  const toastTimer = useRef<number | undefined>(undefined);

  const notify = useCallback<Notify>((text, error = false) => {
    setToast({ text, error });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), error ? 7000 : 4000);
  }, []);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  const range = useMemo(() => {
    if (view === "month") {
      const grid = monthGrid(anchor);
      return { from: grid[0], to: addDays(grid[41], 1) };
    }
    const from = startOfWeek(anchor);
    return { from, to: addDays(from, 7) };
  }, [view, anchor]);

  useEffect(() => {
    api
      .events(range.from, range.to)
      .then(setEvents)
      .catch((err: Error) => notify(`Could not load events: ${err.message}`, true));
  }, [range, tick, notify]);

  useEffect(() => {
    const load = () => {
      api.status().then(setStatus).catch(() => undefined);
      api.alerts().then(setAlerts).catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 60_000);
    return () => window.clearInterval(id);
  }, [tick]);

  const move = (dir: -1 | 0 | 1) => {
    if (dir === 0) setAnchor(new Date());
    else setAnchor((a) => (view === "month" ? addMonths(a, dir) : addDays(a, 7 * dir)));
  };

  const label =
    view === "month"
      ? anchor.toLocaleDateString([], { month: "long", year: "numeric" })
      : `${fmtDate(range.from, { month: "short", day: "numeric" })} to ${fmtDate(addDays(range.to, -1), { month: "short", day: "numeric", year: "numeric" })}`;

  const openEvent = useCallback(
    async (id: number) => {
      try {
        setSelected(await api.event(id));
      } catch (err) {
        notify(`Could not open event: ${(err as Error).message}`, true);
      }
    },
    [notify],
  );

  const onSync = async () => {
    setSyncing(true);
    try {
      const result = await api.sync();
      notify(result.summary);
      refresh();
    } catch (err) {
      notify((err as Error).message, true);
    } finally {
      setSyncing(false);
    }
  };

  const saveForm = async (values: FormValues, id?: number) => {
    if (id) await api.updateEvent(id, values);
    else await api.createEvent(values);
    setEditing(null);
    refresh();
    if (id && selected?.id === id) void openEvent(id);
  };

  const newBlockAt = (start: Date) => {
    const end = new Date(start.getTime() + 60 * 60_000);
    setEditing({ defaults: { start: start.toISOString(), end: end.toISOString(), kind: "study", tentative: true } });
  };

  return (
    <div className="app">
      <TopBar
        view={view}
        onView={setView}
        label={label}
        onMove={move}
        onSync={onSync}
        syncing={syncing}
        status={status}
        alerts={alerts}
        onOpenEvent={openEvent}
        sideOpen={sideOpen}
        onToggleSide={() => setSideOpen((v) => !v)}
        onNew={() => {
          const d = new Date();
          d.setMinutes(0, 0, 0);
          d.setHours(d.getHours() + 1);
          newBlockAt(d);
        }}
      />
      <div className={"main" + (sideOpen ? " with-side" : "")}>
        <section className="calendar">
          {view === "month" ? (
            <MonthView
              anchor={anchor}
              events={events}
              onSelect={(e) => void openEvent(e.id)}
              onDayClick={(d) => {
                const start = new Date(d);
                start.setHours(9, 0, 0, 0);
                newBlockAt(start);
              }}
            />
          ) : (
            <WeekView weekStart={range.from} events={events} onSelect={(e) => void openEvent(e.id)} onSlotClick={newBlockAt} />
          )}
        </section>
        {sideOpen && (
          <SidePanel tab={tab} onTab={setTab} status={status} anchor={anchor} refreshKey={tick} onOpenEvent={openEvent} onChanged={refresh} notify={notify} />
        )}
      </div>
      {selected && (
        <EventDrawer
          event={selected}
          events={events}
          onClose={() => setSelected(null)}
          onEdit={() => setEditing({ event: selected })}
          onChanged={(closed) => {
            refresh();
            if (closed) setSelected(null);
            else void openEvent(selected.id);
          }}
          notify={notify}
        />
      )}
      {editing && <EventForm event={editing.event} defaults={editing.defaults} onCancel={() => setEditing(null)} onSave={saveForm} />}
      {toast && <div className={"toast" + (toast.error ? " error" : "")}>{toast.text}</div>}
    </div>
  );
}
