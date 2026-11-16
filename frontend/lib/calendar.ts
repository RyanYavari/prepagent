// Mirrors backend/models/calendar.py. All backend calls send the session JWT;
// identity is never taken from the request body.
import { API_URL } from "./api";

export interface CalendarStatus {
  connected: boolean;
  status: "active" | "revoked" | null;
  last_synced_at: string | null;
}

export interface SyncResult {
  events_scanned: number;
  candidates: number;
  briefings_created: number;
  needs_confirmation: number;
  ignored: number;
  errors: number;
  truncated: boolean;
  skipped: string | null;
}

export interface Detection {
  id: string;
  status: string;
  event_start: string | null;
  event_title: string | null;
  confidence: number | null;
  company: string | null;
  role: string | null;
  interviewer_names: string[];
  reasons: string[];
}

export class CalendarApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_URL}/calendar${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new CalendarApiError(
      res.status,
      typeof body.detail === "string" ? body.detail : "Request failed",
    );
  }
  return res.json() as Promise<T>;
}

export const getStatus = (t: string) => call<CalendarStatus>("/status", t);
export const getConnectUrl = (t: string) =>
  call<{ url: string }>("/connect", t).then((r) => r.url);
export const completeCallback = (t: string, code: string, state: string) =>
  call<CalendarStatus>("/callback", t, {
    method: "POST",
    body: JSON.stringify({ code, state }),
  });
export const syncCalendar = (t: string) =>
  call<SyncResult>("/sync", t, { method: "POST" });
export const listDetections = (t: string) =>
  call<{ detections: Detection[] }>("/detections", t).then((r) => r.detections);
export const confirmDetection = (t: string, id: string) =>
  call<{ briefing_id: string }>(
    `/detections/${encodeURIComponent(id)}/confirm`,
    t,
    { method: "POST" },
  );
export const dismissDetection = (t: string, id: string) =>
  call<Detection>(`/detections/${encodeURIComponent(id)}/dismiss`, t, {
    method: "POST",
  });
export const disconnectCalendar = (t: string) =>
  call<CalendarStatus>("/connection", t, { method: "DELETE" });

// The backend answers every /calendar route with this 404 when CALENDAR_ENABLED is off,
// so the panel should disappear rather than show an error. Other 404s (for example an
// unknown detection) are ordinary errors.
export const isCalendarUnavailable = (e: unknown) =>
  e instanceof CalendarApiError &&
  e.status === 404 &&
  e.message === "Calendar is not available";

// 401 means the session JWT is bad (sign out). A 409 from /sync means the
// calendar connection itself needs reconnecting, which is not a sign-out.
export const isSessionExpired = (e: unknown) =>
  e instanceof CalendarApiError && e.status === 401;
export const needsReconnect = (e: unknown) =>
  e instanceof CalendarApiError &&
  e.status === 409 &&
  e.message.toLowerCase().includes("reconnect");

export function describeSync(r: SyncResult): string {
  if (r.skipped === "recently_synced") return "Already synced a moment ago.";
  const parts: string[] = [];
  if (r.briefings_created)
    parts.push(`${r.briefings_created} briefing(s) started`);
  if (r.needs_confirmation)
    parts.push(`${r.needs_confirmation} interview(s) to confirm`);
  if (!parts.length) parts.push("No new interviews found");
  if (r.errors) parts.push(`${r.errors} event(s) could not be checked`);
  if (r.truncated) parts.push("only the first 100 events were scanned");
  return parts.join("; ") + ".";
}
