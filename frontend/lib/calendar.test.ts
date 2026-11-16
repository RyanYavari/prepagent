import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CalendarApiError,
  completeCallback,
  confirmDetection,
  describeSync,
  getConnectUrl,
  isSessionExpired,
  needsReconnect,
  syncCalendar,
  type SyncResult,
} from "./calendar";

const sync = (o: Partial<SyncResult> = {}): SyncResult => ({
  events_scanned: 0, candidates: 0, briefings_created: 0, needs_confirmation: 0,
  ignored: 0, errors: 0, truncated: false, skipped: null, ...o,
});

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", f);
  return f;
}

afterEach(() => vi.unstubAllGlobals());

describe("calendar api helpers", () => {
  it("sends the JWT and never puts identity in the body", async () => {
    const f = mockFetch(200, { connected: true, status: "active", last_synced_at: null });
    await completeCallback("jwt-1", "the-code", "the-state");
    const [url, init] = f.mock.calls[0];
    expect(url).toContain("/calendar/callback");
    expect(init.headers.Authorization).toBe("Bearer jwt-1");
    expect(JSON.parse(init.body)).toEqual({ code: "the-code", state: "the-state" });
  });

  it("returns the consent url", async () => {
    mockFetch(200, { url: "https://accounts.google.com/x" });
    expect(await getConnectUrl("t")).toBe("https://accounts.google.com/x");
  });

  it("raises CalendarApiError with the server's generic detail", async () => {
    mockFetch(409, { detail: "Calendar connection expired. Please reconnect." });
    const err = await syncCalendar("t").catch((e) => e);
    expect(err).toBeInstanceOf(CalendarApiError);
    expect(needsReconnect(err)).toBe(true);
    expect(isSessionExpired(err)).toBe(false);
  });

  it("falls back to a generic message for non-JSON errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 500, json: () => Promise.reject(new Error("no json")),
    }));
    const err = await syncCalendar("t").catch((e) => e);
    expect(err.message).toBe("Request failed");
  });

  it("flags an expired session on 401", async () => {
    mockFetch(401, { detail: "Token has expired" });
    const err = await syncCalendar("t").catch((e) => e);
    expect(isSessionExpired(err)).toBe(true);
    expect(needsReconnect(err)).toBe(false);
  });

  it("encodes the detection id in the path", async () => {
    const f = mockFetch(200, { briefing_id: "b1" });
    await confirmDetection("t", "a/b");
    expect(f.mock.calls[0][0]).toContain("/detections/a%2Fb/confirm");
  });
});

describe("describeSync", () => {
  it("summarizes outcomes", () => {
    expect(describeSync(sync())).toBe("No new interviews found.");
    expect(describeSync(sync({ needs_confirmation: 2, errors: 1 }))).toBe(
      "2 interview(s) to confirm; 1 event(s) could not be checked.",
    );
    expect(describeSync(sync({ skipped: "recently_synced" }))).toContain("Already synced");
    expect(describeSync(sync({ truncated: true }))).toContain("first 100");
  });
});

import { CalendarApiError as ApiError, isCalendarUnavailable } from "./calendar";

describe("isCalendarUnavailable", () => {
  it("is true only for the backend's calendar-disabled 404", () => {
    expect(isCalendarUnavailable(new ApiError(404, "Calendar is not available"))).toBe(true);
    expect(isCalendarUnavailable(new ApiError(404, "Detection not found"))).toBe(false);
    expect(isCalendarUnavailable(new ApiError(500, "Calendar is not available"))).toBe(false);
    expect(isCalendarUnavailable(new Error("Calendar is not available"))).toBe(false);
  });
});
