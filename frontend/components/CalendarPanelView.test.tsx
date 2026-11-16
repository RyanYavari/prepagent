import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CalendarStatus, Detection } from "@/lib/calendar";
import { CalendarPanelView, type CalendarPanelViewProps } from "./CalendarPanelView";

const noop = () => {};
const base: CalendarPanelViewProps = {
  status: { connected: false, status: null, last_synced_at: null },
  detections: [], busy: false, message: null, error: null, reconnectRequired: false,
  onConnect: noop, onSync: noop, onDisconnect: noop, onConfirm: noop, onDismiss: noop,
};
const html = (o: Partial<CalendarPanelViewProps> = {}) =>
  renderToStaticMarkup(<CalendarPanelView {...base} {...o} />);
const active: CalendarStatus = { connected: true, status: "active", last_synced_at: null };
const det = (o: Partial<Detection> = {}): Detection => ({
  id: "d1", status: "needs_confirmation", event_start: null, event_title: "Chat",
  confidence: 0.6, company: "Acme", role: "Engineer",
  interviewer_names: ["Jane Doe", "Bob"], reasons: [], ...o,
});

describe("CalendarPanelView", () => {
  it("offers Connect Calendar when not connected", () => {
    const out = html();
    expect(out).toContain("Connect Calendar");
    expect(out).not.toContain("Sync now");
  });

  it("shows loading text and no button before status arrives", () => {
    const out = html({ status: null });
    expect(out).toContain("Checking calendar connection");
    expect(out).not.toContain("Connect Calendar</button>");
  });

  it("shows reconnect prompt when revoked or flagged", () => {
    const revoked = html({ status: { connected: true, status: "revoked", last_synced_at: null } });
    expect(revoked).toContain("Reconnect Calendar");
    expect(revoked).toContain("expired");
    expect(html({ reconnectRequired: true })).toContain("Reconnect Calendar");
  });

  it("shows sync and disconnect when connected, with confirmation list", () => {
    const out = html({ status: active, detections: [det()] });
    expect(out).toContain("Sync now");
    expect(out).toContain("Disconnect");
    expect(out).toContain("Interviews to confirm");
    expect(out).toContain("Acme");
    expect(out).toContain("with Jane Doe, Bob");
    expect(out).toContain("Create briefing");
    expect(out).toContain("Dismiss");
  });

  it("renders extracted fields as escaped plain text", () => {
    const out = html({
      status: active,
      detections: [det({ company: "<img src=x onerror=alert(1)>", event_title: "<script>x</script>" })],
    });
    expect(out).not.toContain("<img src=x");
    expect(out).not.toContain("<script>x");
    expect(out).toContain("&lt;img");
  });

  it("disables confirm when no company was found", () => {
    const out = html({ status: active, detections: [det({ company: null })] });
    expect(out).toContain("Company not found");
    expect(out).toMatch(/disabled=""[^>]*>Create briefing/);
  });

  it("shows errors as alerts and messages", () => {
    const out = html({ status: active, error: "Calendar sync failed", message: "No new interviews found." });
    expect(out).toContain('role="alert"');
    expect(out).toContain("Calendar sync failed");
    expect(out).toContain("No new interviews found.");
  });
});
