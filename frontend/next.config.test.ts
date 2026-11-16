import { afterEach, describe, expect, it } from "vitest";
import nextConfig, { securityHeaders } from "./next.config";

const ORIGINAL = { ...process.env };
afterEach(() => {
  process.env = { ...ORIGINAL };
});

function byKey(list: { key: string; value: string }[]) {
  return Object.fromEntries(list.map((h) => [h.key, h.value]));
}

describe("security headers", () => {
  it("applies to every path through next.config headers()", async () => {
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/:path*");
    const h = byKey(rules[0].headers);
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
  });

  it("ships the CSP as Report-Only with the API origin in connect-src", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com/";
    const h = byKey(securityHeaders("production"));
    expect(h["Content-Security-Policy"]).toBeUndefined();
    const csp = h["Content-Security-Policy-Report-Only"];
    expect(csp).toContain("connect-src 'self' https://api.example.com;");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("default-src 'self'");
  });

  it("leaves the CSP off in development (hot reload needs eval)", () => {
    const h = byKey(securityHeaders("development"));
    expect(h["Content-Security-Policy-Report-Only"]).toBeUndefined();
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
  });

  it("falls back to the local API origin when none is configured", () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    const csp = byKey(securityHeaders("production"))[
      "Content-Security-Policy-Report-Only"
    ];
    expect(csp).toContain("connect-src 'self' http://localhost:8000;");
  });
});
