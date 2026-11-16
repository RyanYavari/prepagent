import { hostnameOf, parseCitations } from "@/lib/citations";

export function SourceLink({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={url}
      className="inline-block align-baseline px-1.5 py-0.5 mx-0.5 rounded bg-blue-50 text-blue-700 text-xs hover:bg-blue-100"
    >
      {hostnameOf(url)} ↗
    </a>
  );
}

export function CitedText({
  text,
  flagUnsourced = false,
}: {
  text: string;
  flagUnsourced?: boolean;
}) {
  const segments = parseCitations(text);
  const hasCitation = segments.some((s) => s.type !== "text");

  return (
    <span>
      {segments.map((seg, i) => {
        if (seg.type === "source") return <SourceLink key={i} url={seg.url} />;
        if (seg.type === "jd") {
          return (
            <span
              key={i}
              className="inline-block align-baseline px-1.5 py-0.5 mx-0.5 rounded-full bg-emerald-50 text-emerald-700 text-xs"
            >
              Job description
            </span>
          );
        }
        if (seg.type === "resume") {
          return (
            <span
              key={i}
              className="inline-block align-baseline px-1.5 py-0.5 mx-0.5 rounded-full bg-purple-50 text-purple-700 text-xs"
            >
              Resume: {seg.section}
            </span>
          );
        }
        return <span key={i}>{seg.text}</span>;
      })}
      {flagUnsourced && !hasCitation && (
        <span className="ml-1 px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-xs">
          no source
        </span>
      )}
    </span>
  );
}
