// Date helpers. The browser zone is the display zone.

export const DAY_MS = 86_400_000;

export const startOfDay = (d: Date): Date => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};

export const addDays = (d: Date, n: number): Date => {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
};

export const addMonths = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth() + n, 1);

/** Monday on or before d. */
export const startOfWeek = (d: Date): Date => addDays(startOfDay(d), -((d.getDay() + 6) % 7));

export const sameDay = (a: Date, b: Date): boolean =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

const pad = (n: number) => String(n).padStart(2, "0");

export const isoDate = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Wall-clock value for an <input type="datetime-local">. */
export const toInput = (d: Date): string => `${isoDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

export const fmtTime = (d: Date): string => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export const fmtDate = (d: Date, opts: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric" }): string =>
  d.toLocaleDateString([], opts);

export function fmtRange(start: Date, end: Date | null, allDay: boolean): string {
  if (allDay) return fmtDate(start, { weekday: "long", month: "long", day: "numeric" });
  const day = fmtDate(start, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  if (!end || end.getTime() === start.getTime()) return `${day}, ${fmtTime(start)}`;
  if (sameDay(start, end)) return `${day}, ${fmtTime(start)} to ${fmtTime(end)}`;
  return `${day}, ${fmtTime(start)} to ${fmtDate(end)}, ${fmtTime(end)}`;
}

/** Six weeks of days for a month grid, Monday first. */
export const monthGrid = (anchor: Date): Date[] => {
  const first = startOfWeek(new Date(anchor.getFullYear(), anchor.getMonth(), 1));
  return Array.from({ length: 42 }, (_, i) => addDays(first, i));
};

export const minutesOfDay = (d: Date): number => d.getHours() * 60 + d.getMinutes();

export function relativeDays(target: Date, now = new Date()): string {
  const days = Math.round((startOfDay(target).getTime() - startOfDay(now).getTime()) / DAY_MS);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

export function ago(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}
