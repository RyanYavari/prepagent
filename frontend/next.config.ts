import type { NextConfig } from "next";

const DEFAULT_API_ORIGIN = "http://localhost:8000";

function apiOrigin(): string {
  const raw = (process.env.NEXT_PUBLIC_API_URL ?? "").trim();
  try {
    return new URL(raw).origin;
  } catch {
    return DEFAULT_API_ORIGIN;
  }
}

// Security headers for every response (specs/deployment.md). The CSP is Report-Only
// first: Next injects inline scripts, so a strict policy needs a browser pass before it
// can be enforced. It is skipped in development, where hot reload needs eval.
export function securityHeaders(
  nodeEnv: string | undefined = process.env.NODE_ENV,
): { key: string; value: string }[] {
  const headers = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    // The OAuth `code` is in the callback page URL, so never send it cross-origin.
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  ];
  if (nodeEnv === "production") {
    headers.push({
      key: "Content-Security-Policy-Report-Only",
      value: [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        `connect-src 'self' ${apiOrigin()}`,
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ].join("; ") + ";",
    });
  }
  return headers;
}

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders() }];
  },
};

export default nextConfig;
