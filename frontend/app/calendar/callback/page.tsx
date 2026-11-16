"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { completeCallback } from "@/lib/calendar";

function CalendarCallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  // The authorization code is single-use; never submit it twice (dev strict mode
  // runs effects twice).
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const token = localStorage.getItem("token");

    if (searchParams.get("error")) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot callback
      setError("Calendar access was not granted.");
      return;
    }
    if (!token) {
      router.push("/");
      return;
    }
    if (!code || !state) {
      setError("No authorization code received from Google.");
      return;
    }
    completeCallback(token, code, state)
      .then(() => router.push("/dashboard"))
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Could not connect calendar"),
      );
  }, [searchParams, router]);

  if (error) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4 text-red-600">
            Calendar connection failed
          </h1>
          <p className="text-gray-600 mb-8">{error}</p>
          <Link
            href="/dashboard"
            className="bg-black text-white px-6 py-3 rounded-lg hover:bg-gray-800"
          >
            Back to dashboard
          </Link>
        </div>
      </main>
    );
  }
  return (
    <main className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-2xl font-bold mb-4">Connecting your calendar...</h1>
        <p className="text-gray-600">Please wait.</p>
      </div>
    </main>
  );
}

export default function CalendarCallback() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen flex items-center justify-center">
          <p className="text-gray-600">Loading...</p>
        </main>
      }
    >
      <CalendarCallbackContent />
    </Suspense>
  );
}
