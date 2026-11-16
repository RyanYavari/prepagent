"use client";

import { useCallback, useEffect, useState } from "react";
import {
  confirmDetection,
  describeSync,
  disconnectCalendar,
  dismissDetection,
  getConnectUrl,
  getStatus,
  isSessionExpired,
  listDetections,
  needsReconnect,
  syncCalendar,
  type CalendarStatus,
  type Detection,
} from "@/lib/calendar";
import { CalendarPanelView } from "./CalendarPanelView";

export function CalendarPanel({
  onSessionExpired,
  onBriefingCreated,
}: {
  onSessionExpired: () => void;
  onBriefingCreated: (briefingId: string) => void;
}) {
  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reconnectRequired, setReconnectRequired] = useState(false);

  // Runs an action with the session token, mapping failures to UI state.
  const run = useCallback(
    async (action: (token: string) => Promise<void>) => {
      const token = localStorage.getItem("token");
      if (!token) {
        onSessionExpired();
        return;
      }
      setBusy(true);
      setError(null);
      try {
        await action(token);
      } catch (e) {
        if (isSessionExpired(e)) onSessionExpired();
        else if (needsReconnect(e)) {
          setReconnectRequired(true);
          setStatus({ connected: true, status: "revoked", last_synced_at: null });
        } else {
          setError(e instanceof Error ? e.message : "Something went wrong");
        }
      } finally {
        setBusy(false);
      }
    },
    [onSessionExpired],
  );

  const sync = useCallback(
    (token: string) =>
      syncCalendar(token).then(async (r) => {
        setMessage(describeSync(r));
        setDetections(await listDetections(token));
      }),
    [],
  );

  // Initial load: status, then (if connected) one sync and the confirm list.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    void run(async (token) => {
      const s = await getStatus(token);
      setStatus(s);
      if (s.connected && s.status === "active") await sync(token);
    });
  }, [run, sync]);

  return (
    <CalendarPanelView
      status={status}
      detections={detections}
      busy={busy}
      message={message}
      error={error}
      reconnectRequired={reconnectRequired}
      onConnect={() =>
        void run(async (token) => {
          window.location.assign(await getConnectUrl(token));
        })
      }
      onSync={() => void run(sync)}
      onDisconnect={() =>
        void run(async (token) => {
          setStatus(await disconnectCalendar(token));
          setDetections([]);
          setReconnectRequired(false);
          setMessage("Calendar disconnected.");
        })
      }
      onConfirm={(id) =>
        void run(async (token) => {
          const r = await confirmDetection(token, id);
          onBriefingCreated(r.briefing_id);
        })
      }
      onDismiss={(id) =>
        void run(async (token) => {
          await dismissDetection(token, id);
          setDetections((ds) => ds.filter((d) => d.id !== id));
        })
      }
    />
  );
}
