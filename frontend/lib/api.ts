// The backend base URL, read once from NEXT_PUBLIC_API_URL.
//
// NEXT_PUBLIC_* values are inlined into the browser bundle at build time, so a Vercel
// build with the variable missing would otherwise silently ship a site that calls
// http://localhost:8000. In a Vercel production build that is an error instead. Local
// development, CI and preview builds keep the localhost fallback.
const DEV_FALLBACK = "http://localhost:8000";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]);

export function resolveApiUrl(
  raw: string | undefined,
  vercelEnv: string | undefined,
): string {
  const value = (raw ?? "").trim().replace(/\/+$/, "");
  if (vercelEnv !== "production") return value || DEV_FALLBACK;

  if (!value) {
    throw new Error(
      "NEXT_PUBLIC_API_URL must be set for production builds (for example https://api.example.com)",
    );
  }
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("NEXT_PUBLIC_API_URL must be a valid https:// URL in production");
  }
  if (url.protocol !== "https:") {
    throw new Error("NEXT_PUBLIC_API_URL must use https in production");
  }
  if (LOCAL_HOSTS.has(url.hostname)) {
    throw new Error("NEXT_PUBLIC_API_URL must not point at localhost in production");
  }
  return value;
}

// VERCEL_ENV exists only on the server at build time; in the browser it is undefined and
// the value inlined from NEXT_PUBLIC_API_URL (already validated by the build) is used.
export const API_URL = resolveApiUrl(
  process.env.NEXT_PUBLIC_API_URL,
  process.env.VERCEL_ENV,
);
