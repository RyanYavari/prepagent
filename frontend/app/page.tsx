"use client";

import Image from "next/image";
import { useState } from "react";
import { API_URL } from "@/lib/api";

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSignIn = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/auth/google`);
      if (!res.ok) {
        throw new Error("Failed to get auth URL");
      }
      const data = await res.json();
      sessionStorage.setItem("oauth_state", data.state);
      window.location.href = data.url;
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      setError(message);
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <Image
          src="/logo.png"
          alt="PrepAgent logo"
          width={120}
          height={120}
          priority
          className="mx-auto mb-6"
        />
        <h1 className="text-6xl font-bold mb-5">PrepAgent</h1>
        <p className="text-foreground/80 text-2xl mb-10">
          AI-powered interview research briefings in under 90 seconds.
        </p>
        {error && <p className="text-red-500 mb-4 text-base">{error}</p>}
        <button
          onClick={handleSignIn}
          disabled={loading}
          className="bg-black text-white text-xl px-10 py-5 rounded-xl hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Redirecting..." : "Sign in with Google"}
        </button>
        <p className="text-base text-foreground/70 mt-8">
          <a href="/privacy" className="underline">Privacy Policy</a>
          {" · "}
          <a href="/tos" className="underline">Terms of Service</a>
          {" · "}
          <a
            href="https://github.com/RyanYavari/prepagent"
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            GitHub
          </a>
        </p>
      </div>
    </main>
  );
}
