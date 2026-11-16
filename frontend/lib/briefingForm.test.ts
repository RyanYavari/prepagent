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
