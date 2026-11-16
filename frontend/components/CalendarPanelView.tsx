import type { CalendarStatus, Detection } from "@/lib/calendar";

// Presentational only: every extracted field is rendered as plain text (React
// escapes it); nothing from a calendar event is ever used as HTML or a URL.
export interface CalendarPanelViewProps {
  status: CalendarStatus | null;
  detections: Detection[];
  busy: boolean;
  message: string | null;
  error: string | null;
  reconnectRequired: boolean;
  onConnect: () => void;
  onSync: () => void;
  onDisconnect: () => void;
  onConfirm: (id: string) => void;
  onDismiss: (id: string) => void;
}

export function CalendarPanelView(p: CalendarPanelViewProps) {
  const connected = p.status?.connected && p.status.status === "active";
  return (
    <section className="border rounded-lg p-4 mb-6" aria-label="Google Calendar">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Calendar</h2>
          <p className="text-sm text-gray-600">
            {p.status === null
              ? "Checking calendar connection..."
              : connected
                ? "Connected. Upcoming interviews are detected from your calendar."
                : p.reconnectRequired || p.status.status === "revoked"
                  ? "Your calendar connection expired. Reconnect to keep detecting interviews."
                  : "Connect Google Calendar to detect interviews automatically (read-only)."}
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          {connected ? (
            <>
              <button
                onClick={p.onSync}
                disabled={p.busy}
                className="border px-3 py-2 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50"
              >
                {p.busy ? "Working..." : "Sync now"}
              </button>
              <button
                onClick={p.onDisconnect}
                disabled={p.busy}
                className="text-sm text-gray-500 hover:text-gray-800 disabled:opacity-50"
              >
                Disconnect
              </button>
            </>
          ) : p.status !== null ? (
            <button
              onClick={p.onConnect}
              disabled={p.busy}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {p.reconnectRequired || p.status.status === "revoked"
                ? "Reconnect Calendar"
                : "Connect Calendar"}
            </button>
          ) : null}
        </div>
      </div>

      {p.message && <p className="mt-3 text-sm text-gray-700">{p.message}</p>}
      {p.error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {p.error}
        </p>
      )}

      {connected && p.detections.length > 0 && (
        <div className="mt-4 space-y-3">
          <h3 className="font-medium">Interviews to confirm</h3>
          {p.detections.map((d) => (
            <div key={d.id} className="border rounded-lg p-3">
              <div className="flex items-start justify-between gap-4">
                <div className="text-sm">
                  <p className="font-semibold">{d.company ?? "Company not found"}</p>
                  {d.role && <p className="text-gray-700">{d.role}</p>}
                  {d.interviewer_names.length > 0 && (
                    <p className="text-gray-600">
                      with {d.interviewer_names.join(", ")}
                    </p>
                  )}
                  {d.event_title && (
                    <p className="text-gray-500">Event: {d.event_title}</p>
                  )}
                  {d.event_start && (
                    <p className="text-gray-500">
                      {new Date(d.event_start).toLocaleString()}
                    </p>
                  )}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => p.onConfirm(d.id)}
                    disabled={p.busy || !d.company}
                    className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
                  >
                    Create briefing
                  </button>
                  <button
                    onClick={() => p.onDismiss(d.id)}
                    disabled={p.busy}
                    className="border px-3 py-1.5 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
