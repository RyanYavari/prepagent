import { describe, expect, it } from "vitest";
import { resolveApiUrl } from "./api";

describe("resolveApiUrl", () => {
  it("falls back to localhost outside a Vercel production build", () => {
    expect(resolveApiUrl(undefined, undefined)).toBe("http://localhost:8000");
    expect(resolveApiUrl("", "preview")).toBe("http://localhost:8000");
    expect(resolveApiUrl(undefined, "development")).toBe("http://localhost:8000");
  });

  it("throws in a Vercel production build when the variable is unset", () => {
    expect(() => resolveApiUrl(undefined, "production")).toThrow(
      /NEXT_PUBLIC_API_URL/,
    );
    expect(() => resolveApiUrl("   ", "production")).toThrow(/NEXT_PUBLIC_API_URL/);
  });

  it("requires https in a production build", () => {
    expect(() => resolveApiUrl("http://api.example.com", "production")).toThrow(
      /https/,
    );
    expect(() => resolveApiUrl("api.example.com", "production")).toThrow(/https/);
  });

  it("never falls back to localhost in production, even for a localhost value", () => {
    expect(() => resolveApiUrl("https://localhost:8000", "production")).toThrow(
      /localhost/,
    );
  });

  it("uses the configured value and strips trailing slashes", () => {
    expect(resolveApiUrl("https://api.example.com", "production")).toBe(
      "https://api.example.com",
    );
    expect(resolveApiUrl("https://api.example.com//", "production")).toBe(
      "https://api.example.com",
    );
    expect(resolveApiUrl("http://localhost:9000/", undefined)).toBe(
      "http://localhost:9000",
    );
  });
});
