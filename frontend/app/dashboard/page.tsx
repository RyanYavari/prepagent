"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type BriefingStatus = "pending" | "running" | "complete" | "failed";

interface Briefing {
  id: string;
  company: string;
  interviewer: string | null;
  role: string | null;
  status: BriefingStatus;
  created_at: string;
}

function StatusBadge({ status }: { status: BriefingStatus }) {
  const styles = {
    pending: "bg-gray-100 text-gray-700",
    running: "bg-blue-100 text-blue-700",
    complete: "bg-green-100 text-green-700",
    failed: "bg-red-100 text-red-700",
  };

  return (
    <span
      className={`px-2 py-1 rounded text-xs font-medium ${styles[status]}`}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [email] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("email");
    }
    return null;
  });
  const [briefings, setBriefings] = useState<Briefing[]>([]);
  const [briefingsLoading, setBriefingsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("token");
    const storedEmail = localStorage.getItem("email");

    if (!token || !storedEmail) {
      router.push("/");
      return;
    }

    // Fetch briefings
    const fetchBriefings = async () => {
      try {
        const res = await fetch(`${API_URL}/briefings?limit=20&offset=0`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

        if (res.status === 401) {
          // Token expired or invalid
          localStorage.removeItem("token");
          localStorage.removeItem("email");
          router.push("/");
          return;
        }

        if (!res.ok) {
          throw new Error("Failed to fetch briefings");
        }

        const data = await res.json();
        setBriefings(data.briefings);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load briefings"
        );
      } finally {
        setBriefingsLoading(false);
      }
    };

    fetchBriefings();
  }, [router]);

  const handleSignOut = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("email");
    router.push("/");
  };

  if (briefingsLoading && !email) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <p className="text-gray-600">Loading...</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold">PrepAgent</h1>
            <p className="text-gray-600">Welcome, {email}</p>
          </div>
          <button
            onClick={handleSignOut}
            className="text-gray-500 hover:text-gray-800 text-sm"
          >
            Sign out
          </button>
        </div>

        <div className="mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold">Briefing History</h2>
            <button
              onClick={() => router.push("/prep/new")}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
            >
              New Briefing
            </button>
          </div>

          {briefingsLoading ? (
            <div className="border rounded-lg p-8 text-center">
              <p className="text-gray-600">Loading briefings...</p>
            </div>
          ) : error ? (
            <div className="border border-red-200 rounded-lg p-8 text-center">
              <p className="text-red-600">{error}</p>
            </div>
          ) : briefings.length === 0 ? (
            <div className="border rounded-lg p-8 text-center">
              <p className="text-gray-500">
                No briefings yet. Start your first interview prep to see
                results here.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {briefings.map((briefing) => (
                <div
                  key={briefing.id}
                  className="border rounded-lg p-4 hover:shadow-sm transition-shadow"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-semibold text-lg">
                          {briefing.company}
                        </h3>
                        <StatusBadge status={briefing.status} />
                      </div>
                      {briefing.role && (
                        <p className="text-gray-700 text-sm mb-1">
                          {briefing.role}
                        </p>
                      )}
                      {briefing.interviewer && (
                        <p className="text-gray-600 text-sm">
                          with {briefing.interviewer}
                        </p>
                      )}
                    </div>
                    <div className="text-right text-sm text-gray-500">
                      {new Date(briefing.created_at).toLocaleDateString()}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
