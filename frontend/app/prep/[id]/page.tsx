"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { BriefingSections } from "@/components/BriefingSections";
import {
  POLL_INTERVAL_MS,
  POLL_MAX_FAILURES,
  POLL_MAX_MS,
  isNotFoundStatus,
  type Briefing,
} from "@/lib/briefing";
import { API_URL } from "@/lib/api";

type Stopped = "timeout" | "errors" | null;

export default function BriefingViewer() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();

  const [ready, setReady] = useState(false);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [stopped, setStopped] = useState<Stopped>(null);
  // Bumped by "Check again" to restart the polling effect.
  const [attempt, setAttempt] = useState(0);

  const failures = useRef(0);

  const fetchOnce = useCallback(
    async (token: string): Promise<"continue" | "stop"> => {
      try {
        const res = await fetch(`${API_URL}/briefings/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        if (res.status === 401) {
          localStorage.removeItem("token");
          localStorage.removeItem("email");
          router.push("/");
          return "stop";
        }
        if (isNotFoundStatus(res.status)) {
          setNotFound(true);
          return "stop";
        }
        if (!res.ok) throw new Error(`Request failed (${res.status})`);

        const data: Briefing = await res.json();
        failures.current = 0;
        setPollError(null);
        setBriefing(data);
        return data.status === "pending" || data.status === "running"
          ? "continue"
          : "stop";
      } catch (err) {
        failures.current += 1;
        setPollError(
          err instanceof Error ? err.message : "Failed to load briefing"
        );
        if (failures.current >= POLL_MAX_FAILURES) {
          setStopped("errors");
          return "stop";
        }
        return "continue";
      }
    },
    [id, router]
  );

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();
    failures.current = 0;

    const tick = async () => {
      const next = await fetchOnce(token);
      if (cancelled) return;
      setReady(true);
      if (next === "stop") return;
      if (Date.now() - startedAt >= POLL_MAX_MS) {
        setStopped("timeout");
        return;
      }
      timer = setTimeout(tick, POLL_INTERVAL_MS);
    };

    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [fetchOnce, router, attempt]);

  const checkAgain = () => {
    setStopped(null);
    setPollError(null);
    setAttempt((a) => a + 1);
  };

  if (!ready) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <p className="text-gray-600">Loading...</p>
      </main>
    );
  }

  const back = (
    <Link href="/dashboard" className="text-sm text-gray-500 hover:text-gray-800">
      ← Back to dashboard
    </Link>
  );

  if (notFound) {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-3xl mx-auto">
          {back}
          <div className="border rounded-lg p-8 text-center mt-6">
            <p className="text-gray-700">Briefing not found.</p>
          </div>
        </div>
      </main>
    );
  }

  if (!briefing) {
    return (
      <main className="min-h-screen p-8">
        <div className="max-w-3xl mx-auto">
          {back}
          <div className="border border-red-200 rounded-lg p-8 text-center mt-6">
            <p className="text-red-600 mb-3">
              {pollError ?? "Failed to load briefing"}
            </p>
            <button
              onClick={checkAgain}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
            >
              Check again
            </button>
          </div>
        </div>
      </main>
    );
  }

  const inProgress =
    briefing.status === "pending" || briefing.status === "running";

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-3xl mx-auto">
        {back}

        <header className="mt-4 mb-6">
          <h1 className="text-3xl font-bold">{briefing.company}</h1>
          {briefing.role && <p className="text-gray-700">{briefing.role}</p>}
          {briefing.interviewer && (
            <p className="text-gray-600 text-sm">with {briefing.interviewer}</p>
          )}
        </header>

        {pollError && (
          <p
            role="status"
            className="mb-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2"
          >
            Couldn&apos;t refresh: {pollError}
          </p>
        )}

        {inProgress && !stopped && (
          <div className="border rounded-lg p-8 text-center" aria-live="polite">
            <p className="font-medium mb-1">
              {briefing.status === "pending"
                ? "Queued, starting soon..."
                : "Researching and writing your briefing..."}
            </p>
            <p className="text-sm text-gray-500">
              This usually takes under 90 seconds. This page updates
              automatically.
            </p>
          </div>
        )}

        {inProgress && stopped && (
          <div className="border border-amber-300 bg-amber-50 rounded-lg p-8 text-center">
            <p className="text-amber-900 mb-3">
              {stopped === "timeout"
                ? "This briefing is taking longer than expected."
                : "We lost contact with the server."}
            </p>
            <button
              onClick={checkAgain}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
            >
              Check again
            </button>
          </div>
        )}

        {briefing.status === "failed" && (
          <div className="border border-red-200 bg-red-50 rounded-lg p-8 text-center">
            <p className="text-red-700 font-medium mb-1">
              Briefing generation failed.
            </p>
            <p className="text-sm text-red-600">
              Go back and try creating it again.
            </p>
          </div>
        )}

        {briefing.status === "complete" &&
          (briefing.content ? (
            <BriefingSections
              content={briefing.content}
              hasInterviewer={!!briefing.interviewer}
            />
          ) : (
            <div className="border rounded-lg p-8 text-center">
              <p className="text-gray-600">No content was generated.</p>
            </div>
          ))}
      </div>
    </main>
  );
}
