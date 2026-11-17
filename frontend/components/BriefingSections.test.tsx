import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { BriefingContent } from "@/lib/briefing";
import { BriefingSections } from "./BriefingSections";

const empty: BriefingContent = {
  company_overview: {
    summary: "", recent_news: [], tech_stack: [], culture_notes: "", sources: [],
  },
  interviewer_profile: {
    summary: "", background: "", shared_interests: [],
    conversation_starters: [], sources: [],
  },
  role_insights: {
    key_requirements: [], resume_alignment: [], potential_gaps: [], sources: [],
  },
  talking_points: {
    talking_points: [], suggested_questions: [], stories_to_prepare: [],
  },
  warnings: [],
};

const html = (c: BriefingContent, hasInterviewer = true) =>
  renderToStaticMarkup(<BriefingSections content={c} hasInterviewer={hasInterviewer} />);

describe("BriefingSections", () => {
  it("renders source links safely and resume chips", () => {
    const out = html({
      ...empty,
      talking_points: {
        ...empty.talking_points,
        talking_points: [
          "Scaled infra [Resume: Experience] and read [Source: https://www.stripe.com/blog]",
        ],
      },
    });
    expect(out).toContain('href="https://www.stripe.com/blog"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain("stripe.com");
    expect(out).toContain("Resume: Experience");
    expect(out).not.toContain("[Source:");
    expect(out).not.toContain("no source");
  });

  it("shows a Job description chip and a Key requirements indicator for [JD] items", () => {
    const out = html({
      ...empty,
      role_insights: {
        ...empty.role_insights,
        key_requirements: ["4+ years of Go [JD]"],
        resume_alignment: ["Built Go services [JD] [Resume: Experience]"],
      },
    });
    expect(out).not.toContain("[JD]");
    expect(out).toContain("Job description");
    expect(out).toContain("From job description");
    expect(out).not.toContain("no source"); // a [JD] item counts as sourced
    // the indicator belongs to the Key requirements list only
    expect(out.match(/From job description/g)).toHaveLength(1);
    const keyReq = out.split("Key requirements")[1].split("Resume alignment")[0];
    expect(keyReq).toContain("From job description");
  });

  it("shows no job-description indicator for a briefing without [JD]", () => {
    const out = html({
      ...empty,
      role_insights: {
        ...empty.role_insights,
        key_requirements: ["Likely needs Go [Source: https://stripe.com/jobs]"],
      },
    });
    expect(out).not.toContain("Job description");
    expect(out).not.toContain("From job description");
  });

  it("flags untagged generated items", () => {
    const out = html({
      ...empty,
      talking_points: { ...empty.talking_points, talking_points: ["Plain claim"] },
    });
    expect(out).toContain("no source");
  });

  it("shows warnings prominently with a count, none when empty", () => {
    const out = html({ ...empty, warnings: ["Limited info", "Wrong person?"] });
    expect(out).toContain('role="alert"');
    expect(out).toContain("2 warnings");
    expect(out).toContain("Limited info");
    expect(html(empty)).not.toContain('role="alert"');
  });

  it("shows empty-section messages and renders all four sections in order", () => {
    const out = html(empty, false);
    expect(out).toContain("No interviewer provided.");
    const order = ["Company Overview", "Interviewer Profile", "Role Insights", "Talking Points"]
      .map((t) => out.indexOf(t));
    expect(order.every((n) => n >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });
});
