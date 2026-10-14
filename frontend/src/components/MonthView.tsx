import type { CalEvent } from "../api";
import { addDays, fmtTime, isoDate, monthGrid, sameDay, startOfDay } from "../lib/dates";

interface Props {
  anchor: Date;
  events: CalEvent[];
  onSelect: (e: CalEvent) => void;
  onDayClick: (d: Date) => void;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_CHIPS = 4;

export function chipClass(e: CalEvent): string {
  const parts = ["chip", `k-${e.kind}`];
  if (e.status === "proposed") parts.push("proposed");
  if (e.tentative) parts.push("tentative");
  if (e.conflicts.length) parts.push("conflict");
  return parts.join(" ");
}

/** Which calendar days an event appears on. Timed events show on their start day. */
export function daysOf(e: CalEvent): string[] {
  const start = new Date(e.start);
  if (!e.all_day) return [isoDate(start)];
  const end = e.end ? new Date(e.end) : addDays(start, 1);
  const out: string[] = [];
  for (let d = startOfDay(start); d < end && out.length < 60; d = addDays(d, 1)) out.push(isoDate(d));
  return out.length ? out : [isoDate(start)];
}

export default function MonthView({ anchor, events, onSelect, onDayClick }: Props) {
  const days = monthGrid(anchor);
  const today = new Date();
  const byDay = new Map<string, CalEvent[]>();
  for (const e of events) {
    for (const key of daysOf(e)) byDay.set(key, [...(byDay.get(key) ?? []), e]);
  }
  for (const list of byDay.values()) {
    list.sort((a, b) => Number(b.all_day) - Number(a.all_day) || a.start.localeCompare(b.start));
  }

  return (
    <div className="month-wrap">
      <div className="weekdays">
        {WEEKDAYS.map((d) => (
          <div key={d}>{d}</div>
        ))}
      </div>
      <div className="month">
        {days.map((d) => {
          const list = byDay.get(isoDate(d)) ?? [];
          const other = d.getMonth() !== anchor.getMonth();
          return (
            <div key={d.toISOString()} className={"cell" + (other ? " other" : "") + (sameDay(d, today) ? " today" : "")} onClick={() => onDayClick(d)}>
              <span className="day">{d.getDate()}</span>
              {list.slice(0, MAX_CHIPS).map((e) => (
                <div
                  key={e.id}
                  className={chipClass(e)}
                  title={e.title}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    onSelect(e);
                  }}
                >
                  {!e.all_day && <span className="time">{fmtTime(new Date(e.start))}</span>}
                  <span>{e.title}</span>
                </div>
              ))}
              {list.length > MAX_CHIPS && <span className="more">+{list.length - MAX_CHIPS} more</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
