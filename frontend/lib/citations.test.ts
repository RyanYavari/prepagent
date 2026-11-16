import { describe, expect, it } from "vitest";
import { hostnameOf, parseCitations } from "./citations";

describe("parseCitations", () => {
  it("parses a source tag and strips it from text", () => {
    expect(parseCitations("Raised funding [Source: https://example.com/a]")).toEqual([
      { type: "text", text: "Raised funding " },
      { type: "source", url: "https://example.com/a" },
    ]);
  });

  it("parses resume tags and trims whitespace", () => {
    expect(parseCitations("[Resume: Experience] x [Resume:  Skills ]")).toEqual([
      { type: "resume", section: "Experience" },
      { type: "text", text: " x " },
      { type: "resume", section: "Skills" },
    ]);
  });

  it("keeps order for mixed tags", () => {
    const segs = parseCitations(
      "a [Source: http://x.io] b [Resume: Projects] c"
    );
    expect(segs.map((s) => s.type)).toEqual([
      "text", "source", "text", "resume", "text",
    ]);
  });

  it("does not link non-http urls", () => {
    expect(parseCitations("[Source: javascript:alert(1)]")).toEqual([
      { type: "text", text: "[Source: javascript:alert(1)]" },
    ]);
    expect(parseCitations("[Source: some words]")).toEqual([
      { type: "text", text: "[Source: some words]" },
    ]);
  });

  it("parses a bare [JD] tag as a job-description segment", () => {
    expect(parseCitations("Needs 4+ years of Go [JD]")).toEqual([
      { type: "text", text: "Needs 4+ years of Go " },
      { type: "jd" },
    ]);
    expect(
      parseCitations("Built Go services [JD] [Resume: Experience]").map((s) => s.type)
    ).toEqual(["text", "jd", "text", "resume"]);
  });

  it("only accepts the exact [JD] tag", () => {
    for (const bad of ["[jd]", "[JD: x]", "[ JD ]", "[JDX]", "[JD"]) {
      expect(parseCitations(`a ${bad}`)).toEqual([{ type: "text", text: `a ${bad}` }]);
    }
  });

  it("handles no tags, empty and unclosed tags", () => {
    expect(parseCitations("plain")).toEqual([{ type: "text", text: "plain" }]);
    expect(parseCitations("")).toEqual([]);
    expect(parseCitations("x [Source: https://x")).toEqual([
      { type: "text", text: "x [Source: https://x" },
    ]);
  });
});

describe("hostnameOf", () => {
  it("returns hostname without www", () => {
    expect(hostnameOf("https://www.example.com/a")).toBe("example.com");
  });
  it("falls back to the input on bad urls", () => {
    expect(hostnameOf("nope")).toBe("nope");
  });
});
