// Types mirror backend/dynamical/api/schemas.py, plus a small fetch wrapper.

export type EventStatus = "confirmed" | "proposed" | "rejected" | "cancelled";

export interface CalEvent {
  id: number;
  title: string;
  description: string | null;
  location: string | null;
  start: string;
  end: string | null;
  all_day: boolean;
  tz: string;
  kind: string;
  status: EventStatus;
  tentative: boolean;
  source: string;
  source_message_id: string | null;
  thread_id: string | null;
  confidence: number | null;
  relationship: string | null;
  rationale: string | null;
  created_at: string;
  updated_at: string;
  conflicts: number[];
  source_subject: string | null;
  source_from: string | null;
}

export interface EventInput {
  title: string;
  start: string;
  end?: string | null;
  all_day?: boolean;
  kind?: string;
  tentative?: boolean;
  location?: string | null;
  description?: string | null;
  status?: EventStatus;
}

export interface Task {
  id: number;
  title: string;
  details: string | null;
  due: string | null;
  kind: string;
  status: "open" | "done";
  priority: number;
  event_id: number | null;
  source_message_id: string | null;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool_calls: { name: string; args: Record<string, unknown> }[] | null;
  created_at: string;
}

export interface Alert {
  severity: "high" | "medium" | "low";
  kind: string;
  message: string;
  event_id: number | null;
  count: number | null;
}

export interface Suggestion {
  start: string;
  end: string;
  minutes: number;
  when: string;
}

export interface MailRecord {
  id: string;
  subject: string;
  from_name: string;
  from_email: string;
  date: string;
  snippet: string;
  labels: string[];
  has_ics: boolean;
  triage_decision: string | null;
  triage_score: number | null;
  triage_reasons: string[];
  status: string;
  error: string | null;
  extraction: { relationship?: string; summary?: string; rationale?: string } | null;
  body_excerpt: string;
  event_ids: number[];
}

export interface DigestEvent {
  id: number;
  title: string;
  when: string;
  kind: string;
  status: string;
  tentative: boolean;
  location: string | null;
  days_away?: number;
  prep_minutes_planned?: number;
}

export interface DigestTask {
  id: number;
  title: string;
  due: string | null;
  kind: string;
  details: string | null;
}

export interface Digest {
  scope: "day" | "week";
  start: string;
  end: string;
  days: { date: string; label: string; events: DigestEvent[]; free: { when: string; minutes: number }[]; free_minutes: number }[];
  tasks_due: DigestTask[];
  tasks_overdue: DigestTask[];
  tasks_undated: DigestTask[];
  coming_up: DigestEvent[];
  conflicts: { a: DigestEvent; b: DigestEvent; severity: string; overlap_minutes: number }[];
  proposed: DigestEvent[];
  suggestions: string[];
  total_free_minutes: number;
  narrative: string | null;
}

export interface AppStatus {
  version: string;
  timezone: string;
  user_email: string | null;
  llm: { provider: string; enabled: boolean; model: string | null };
  gmail: { authorized: boolean; credentials_present: boolean; last_sync: string | null };
  counts: { events: Record<string, number>; messages: Record<string, number>; open_tasks: number };
}

export interface SyncResult {
  report: Record<string, unknown>;
  summary: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // keep the status text
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const patch = (body: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(body) });
const del: RequestInit = { method: "DELETE" };

function query(params: Record<string, string | number | boolean | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export const api = {
  status: () => call<AppStatus>("/api/status"),
  events: (from: Date, to: Date) => call<CalEvent[]>(`/api/events${query({ from: from.toISOString(), to: to.toISOString() })}`),
  event: (id: number) => call<CalEvent>(`/api/events/${id}`),
  createEvent: (body: EventInput) => call<CalEvent>("/api/events", json(body)),
  updateEvent: (id: number, body: Partial<EventInput>) => call<CalEvent>(`/api/events/${id}`, patch(body)),
  deleteEvent: (id: number) => call<void>(`/api/events/${id}`, del),
  suggest: (id: number, minutes: number) => call<{ suggestions: Suggestion[] }>(`/api/events/${id}/suggest${query({ minutes })}`),
  proposals: () => call<CalEvent[]>("/api/proposals"),
  accept: (id: number) => call<CalEvent>(`/api/proposals/${id}/accept`, { method: "POST" }),
  reject: (id: number) => call<CalEvent>(`/api/proposals/${id}/reject`, { method: "POST" }),
  digest: (scope: "day" | "week", date: string, narrative: boolean) => call<Digest>(`/api/digest${query({ scope, date, narrative })}`),
  alerts: () => call<Alert[]>("/api/alerts"),
  tasks: () => call<Task[]>("/api/tasks"),
  createTask: (body: { title: string; due?: string | null; kind?: string }) => call<Task>("/api/tasks", json(body)),
  updateTask: (id: number, body: Partial<Task>) => call<Task>(`/api/tasks/${id}`, patch(body)),
  deleteTask: (id: number) => call<void>(`/api/tasks/${id}`, del),
  mail: (limit = 100) => call<MailRecord[]>(`/api/messages${query({ limit })}`),
  chat: () => call<ChatMessage[]>("/api/chat"),
  send: (message: string) => call<ChatMessage>("/api/chat", json({ message })),
  clearChat: () => call<void>("/api/chat", del),
  sync: (body: { days?: number; full?: boolean } = {}) => call<SyncResult>("/api/sync", json(body)),
  retryPending: () => call<SyncResult>("/api/ingest/pending", { method: "POST" }),
};
