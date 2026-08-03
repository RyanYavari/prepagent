"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AuthCallback() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get("code");
      const stateFromGoogle = searchParams.get("state");

      if (!code) {
        setError("No authorization code received from Google.");
        return;
      }

      const storedState = sessionStorage.getItem("oauth_state");
      if (!stateFromGoogle || stateFromGoogle !== storedState) {
        setError("Invalid state parameter. Please try signing in again.");
        return;
      }
      sessionStorage.removeItem("oauth_state");

      try {
        const res = await fetch(
          `${API_URL}/auth/callback?code=${encodeURIComponent(code)}`
        );

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Authentication failed");
        }

        const data = await res.json();
        localStorage.setItem("token", data.token);
        localStorage.setItem("email", data.email);
        router.push("/dashboard");
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Authentication failed";
        setError(message);
      }
    };

    handleCallback();
  }, [searchParams, router]);

  if (error) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4 text-red-600">
            Authentication Error
          </h1>
          <p className="text-gray-600 mb-8">{error}</p>
          <a
            href="/"
            className="bg-black text-white px-6 py-3 rounded-lg hover:bg-gray-800"
          >
            Try Again
          </a>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-2xl font-bold mb-4">Signing you in...</h1>
        <p className="text-gray-600">
          Please wait while we complete authentication.
        </p>
      </div>
    </main>
  );
}
