import { describe, expect, it } from "vitest";
import { isNotFoundStatus } from "./briefing";

describe("isNotFoundStatus", () => {
  it("treats 404 and 422 as not found", () => {
    expect(isNotFoundStatus(404)).toBe(true);
    expect(isNotFoundStatus(422)).toBe(true);
  });
  it("does not treat other statuses as not found", () => {
    for (const s of [200, 401, 403, 500, 503]) {
      expect(isNotFoundStatus(s)).toBe(false);
    }
  });
});
