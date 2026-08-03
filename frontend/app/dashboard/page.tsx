"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function Dashboard() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    const storedEmail = localStorage.getItem("email");

    if (!token || !storedEmail) {
      router.push("/");
      return;
    }

    setEmail(storedEmail);
    setLoading(false);
  }, [router]);

  const handleSignOut = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("email");
    router.push("/");
  };

  if (loading) {
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

        <div className="border rounded-lg p-8 text-center">
          <h2 className="text-xl font-semibold mb-2">Briefing History</h2>
          <p className="text-gray-500">
            No briefings yet. Start your first interview prep to see results
            here.
          </p>
        </div>
      </div>
    </main>
  );
}
