import { useEffect, useState } from "react";
import type { CalEvent } from "../api";
import { addDays, fmtTime, minutesOfDay, sameDay } from "../lib/dates";

interface Props {
  weekStart: Date;
  events: CalEvent[];
  onSelect: (e: CalEvent) => void;
  onSlotClick: (start: Date) => void;
}

const START_HOUR = 6;
const END_HOUR = 24;
const PX_PER_MIN = 0.9;
const HEIGHT = (END_HOUR - START_HOUR) * 60 * PX_PER_MIN;

interface Placed {
  event: CalEvent;
  top: number;
  height: number;
  lane: number;
  lanes: number;
  start: Date;
  end: Date;
}

/** Assign overlapping events to side-by-side lanes. */
function layout(items: { event: CalEvent; start: Date; end: Date }[]): Placed[] {
  const sorted = [...items].sort((a, b) => a.start.getTime() - b.start.getTime() || b.end.getTime() - a.end.getTime());
  const out: Placed[] = [];
  let cluster: Placed[] = [];
  let clusterEnd = 0;
  let laneEnds: number[] = [];

  const flush = () => {
    for (const p of cluster) p.lanes = laneEnds.length;
    out.push(...cluster);
    cluster = [];
    laneEnds = [];
  };

  for (const it of sorted) {
    if (cluster.length && it.start.getTime() >= clusterEnd) flush();
    let lane = laneEnds.findIndex((end) => end <= it.start.getTime());
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(0);
    }
    laneEnds[lane] = it.end.getTime();
    clusterEnd = Math.max(clusterEnd, it.end.getTime());
    const topMin = minutesOfDay(it.start) - START_HOUR * 60;
    const durMin = Math.max(20, (it.end.getTime() - it.start.getTime()) / 60_000);
    cluster.push({ event: it.event, start: it.start, end: it.end, lane, lanes: 1, top: Math.max(0, topMin * PX_PER_MIN), height: Math.max(18, durMin * PX_PER_MIN) });
  }
  flush();
  return out;
}

export default function WeekView({ weekStart, events, onSelect, onSlotClick }: Props) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const hours = Array.from({ length: END_HOUR - START_HOUR }, (_, i) => START_HOUR + i);

  const perDay = days.map((day) => {
    const dayStart = day.getTime();
    const dayEnd = addDays(day, 1).getTime();
    const allDay: CalEvent[] = [];
    const timed: { event: CalEvent; start: Date; end: Date }[] = [];
    for (const e of events) {
      const s = new Date(e.start).getTime();
      const en = e.end ? new Date(e.end).getTime() : s + 60 * 60_000;
      if (en <= dayStart || s >= dayEnd) continue;
      if (e.all_day || en - s >= 24 * 60 * 60_000) {
        allDay.push(e);
        continue;
      }
      const start = new Date(Math.max(s, dayStart));
      const end = new Date(Math.min(Math.max(en, s + 20 * 60_000), dayEnd - 1));
      timed.push({ event: e, start, end });
    }
    return { day, allDay, placed: layout(timed) };
  });

  const clickSlot = (day: Date, ev: React.MouseEvent<HTMLDivElement>) => {
    const rect = ev.currentTarget.getBoundingClientRect();
    const minutes = (ev.clientY - rect.top) / PX_PER_MIN + START_HOUR * 60;
    const rounded = Math.round(minutes / 30) * 30;
    const start = new Date(day);
    start.setHours(Math.floor(rounded / 60), rounded % 60, 0, 0);
    onSlotClick(start);
  };

  const blockClass = (e: CalEvent) =>
    ["block", `k-${e.kind}`, e.status === "proposed" ? "proposed" : "", e.tentative ? "tentative" : "", e.conflicts.length ? "conflict" : ""].join(" ");

  return (
    <div className="week" style={{ gridTemplateRows: "auto auto auto" }}>
      <div className="corner" />
      {days.map((d) => (
        <div key={d.toISOString()} className={"dayhead" + (sameDay(d, now) ? " today" : "")}>
          {d.toLocaleDateString([], { weekday: "short" })}
          <strong>{d.getDate()}</strong>
        </div>
      ))}
      <div className="corner small muted" style={{ padding: "4px 6px", textAlign: "right" }}>
        all day
      </div>
      {perDay.map(({ day, allDay }) => (
        <div key={day.toISOString()} className="allday">
          {allDay.map((e) => (
            <div key={e.id} className={"chip k-" + e.kind + (e.status === "proposed" ? " proposed" : "")} onClick={() => onSelect(e)} title={e.title}>
              {e.title}
            </div>
          ))}
        </div>
      ))}
      <div className="gutter" style={{ height: HEIGHT }}>
        {hours.map((h) => (
          <div key={h} className="hour" style={{ top: (h - START_HOUR) * 60 * PX_PER_MIN }}>
            {new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" })}
          </div>
        ))}
      </div>
      {perDay.map(({ day, placed }) => (
        <div key={day.toISOString()} className="col" style={{ height: HEIGHT }} onClick={(ev) => clickSlot(day, ev)}>
          {hours.map((h) => (
            <div key={h}>
              <div className="line" style={{ top: (h - START_HOUR) * 60 * PX_PER_MIN }} />
              <div className="line half" style={{ top: ((h - START_HOUR) * 60 + 30) * PX_PER_MIN }} />
            </div>
          ))}
          {sameDay(day, now) && minutesOfDay(now) >= START_HOUR * 60 && <div className="nowline" style={{ top: (minutesOfDay(now) - START_HOUR * 60) * PX_PER_MIN }} />}
          {placed.map((p) => (
            <div
              key={p.event.id}
              className={blockClass(p.event)}
              style={{ top: p.top, height: p.height, left: `calc(${(100 / p.lanes) * p.lane}% + 2px)`, width: `calc(${100 / p.lanes}% - 4px)` }}
              title={p.event.title}
              onClick={(ev) => {
                ev.stopPropagation();
                onSelect(p.event);
              }}
            >
              <span>{p.event.title}</span>
              {p.height > 30 && (
                <span className="t">
                  {fmtTime(p.start)}
                  {p.event.kind !== "deadline" && ` – ${fmtTime(p.end)}`}
                </span>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
