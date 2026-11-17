import { describe, expect, it } from "vitest";
import {
  JD_MAX_CHARS,
  buildPayload,
  jobDescriptionStatus,
  type BriefingFormData,
} from "./briefingForm";

const base: BriefingFormData = {
  company: " Stripe ",
  interviewer: "",
  role: "",
  interview_date: "",
  resume_text: "",
  job_description: "",
};

describe("buildPayload", () => {
  it("omits job_description when empty or whitespace", () => {
    expect(buildPayload(base)).toEqual({ company: "Stripe" });
    expect("job_description" in buildPayload({ ...base, job_description: "  \n " })).toBe(
      false
    );
  });

  it("sends the trimmed job description when present", () => {
    expect(buildPayload({ ...base, job_description: "  Go engineer\n" })).toEqual({
      company: "Stripe",
      job_description: "Go engineer",
    });
  });
});

describe("jobDescriptionStatus", () => {
  it("counts what will be sent and allows exactly the limit", () => {
    expect(jobDescriptionStatus("  abc  ")).toMatchObject({ count: 3, over: false });
    expect(jobDescriptionStatus("a".repeat(JD_MAX_CHARS)).over).toBe(false);
  });

  it("blocks over the limit and says so", () => {
    const s = jobDescriptionStatus("a".repeat(JD_MAX_CHARS + 1));
    expect(s.over).toBe(true);
    expect(s.message).toContain("12,000");
  });

  it("counts characters, not UTF-16 units, like the server", () => {
    expect(jobDescriptionStatus("😀".repeat(JD_MAX_CHARS)).over).toBe(false);
  });
});

import { blockedMessage } from "./briefingForm";

describe("blockedMessage", () => {
  it("explains a daily limit with a rounded wait", () => {
    expect(blockedMessage(429, "Daily briefing limit reached", "7200")).toBe(
      "Daily briefing limit reached. You can try again in about 2 hours.",
    );
    expect(blockedMessage(429, "Daily briefing limit reached", "1800")).toBe(
      "Daily briefing limit reached. You can try again in about 30 minutes.",
    );
    expect(blockedMessage(429, "Daily briefing limit reached", "30")).toBe(
      "Daily briefing limit reached. You can try again in a minute.",
    );
  });

  it("works without a usable Retry-After", () => {
    expect(blockedMessage(429, "Daily briefing limit reached", null)).toBe(
      "Daily briefing limit reached. Please try again later.",
    );
    expect(blockedMessage(429, "Too many requests", "abc")).toBe(
      "Too many requests. Please try again later.",
    );
  });

  it("falls back to generic copy when the 429 has no detail", () => {
    expect(blockedMessage(429, undefined, null)).toBe(
      "Too many requests. Please try again later.",
    );
  });

  it("says briefings are paused for 503", () => {
    expect(blockedMessage(503, "Briefing creation is temporarily unavailable", null)).toBe(
      "Briefing creation is temporarily unavailable. Please try again later.",
    );
    expect(blockedMessage(503, undefined, null)).toBe(
      "Briefing creation is temporarily unavailable. Please try again later.",
    );
  });

  it("returns null for other statuses", () => {
    expect(blockedMessage(500, "x", null)).toBeNull();
    expect(blockedMessage(422, [], null)).toBeNull();
  });
});
