export type Segment =
  | { type: "text"; text: string }
  | { type: "source"; url: string }
  | { type: "resume"; section: string };

// Mirrors _SOURCE_TAG / _RESUME_TAG in backend/agents/synthesis.py.
const TAG = /\[(Source|Resume):\s*([^\]]+?)\s*\]/g;
const HTTP_URL = /^https?:\/\/\S+$/i;

export function parseCitations(text: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  let pending = ""; // text accumulated, including rejected tags

  const flush = () => {
    if (pending) segments.push({ type: "text", text: pending });
    pending = "";
  };

  for (const m of text.matchAll(TAG)) {
    const index = m.index ?? 0;
    pending += text.slice(last, index);
    last = index + m[0].length;
    const [raw, kind, value] = m;
    if (kind === "Resume") {
      flush();
      segments.push({ type: "resume", section: value });
    } else if (HTTP_URL.test(value)) {
      flush();
      segments.push({ type: "source", url: value });
    } else {
      pending += raw; // not a safe URL: keep as plain text
    }
  }
  pending += text.slice(last);
  flush();
  return segments;
}

export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
