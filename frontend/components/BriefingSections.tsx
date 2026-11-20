import type { ReactNode } from "react";
import type { BriefingContent } from "@/lib/briefing";
import { parseCitations } from "@/lib/citations";
import { CitedText, SourceLink } from "./CitedText";

// True when at least one item was grounded in the pasted job description.
function fromJobDescription(items: string[]): boolean {
  return items.some((item) => parseCitations(item).some((s) => s.type === "jd"));
}

function List({
  title,
  items,
  flagUnsourced = false,
  jobDescriptionNote = false,
}: {
  title: string;
  items: string[];
  flagUnsourced?: boolean;
  jobDescriptionNote?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <div className="mb-4">
      <h4 className="text-base font-semibold text-foreground mb-1">
        {title}
        {jobDescriptionNote && (
          <span className="ml-2 align-middle px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-xs font-normal">
            From job description
          </span>
        )}
      </h4>
      <ul className="list-disc pl-5 space-y-1 text-foreground">
        {items.map((item, i) => (
          <li key={i}>
            <CitedText text={item} flagUnsourced={flagUnsourced} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function Text({ title, text }: { title?: string; text: string }) {
  if (!text) return null;
  return (
    <div className="mb-4">
      {title && (
        <h4 className="text-base font-semibold text-foreground mb-1">{title}</h4>
      )}
      <p className="text-foreground whitespace-pre-line">
        <CitedText text={text} />
      </p>
    </div>
  );
}

function Sources({ urls }: { urls: string[] }) {
  if (urls.length === 0) return null;
  return (
    <div className="mb-2">
      <h4 className="text-base font-semibold text-foreground mb-1">Sources</h4>
      <div className="flex flex-wrap gap-1">
        {urls.map((u) => (
          <SourceLink key={u} url={u} />
        ))}
      </div>
    </div>
  );
}

function Section({
  title,
  empty,
  emptyText = "No information available.",
  children,
}: {
  title: string;
  empty: boolean;
  emptyText?: string;
  children: ReactNode;
}) {
  return (
    <section className="border rounded-lg p-5 mb-5">
      <h3 className="text-2xl font-semibold mb-4">{title}</h3>
      {empty ? <p className="text-foreground/70 text-sm">{emptyText}</p> : children}
    </section>
  );
}

export function WarningsBox({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div
      role="alert"
      className="border border-amber-300 bg-amber-50 rounded-lg p-4 mb-6"
    >
      <p className="font-semibold text-amber-900 mb-2">
        {warnings.length} {warnings.length === 1 ? "warning" : "warnings"} about
        this briefing
      </p>
      <ul className="list-disc pl-5 space-y-1 text-amber-900 text-sm">
        {warnings.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

export function BriefingSections({
  content,
  hasInterviewer,
}: {
  content: BriefingContent;
  hasInterviewer: boolean;
}) {
  const c = content.company_overview;
  const i = content.interviewer_profile;
  const r = content.role_insights;
  const t = content.talking_points;

  const companyEmpty =
    !c.summary &&
    !c.culture_notes &&
    c.recent_news.length + c.tech_stack.length + c.sources.length === 0;
  const interviewerEmpty =
    !i.summary &&
    !i.background &&
    i.shared_interests.length +
      i.conversation_starters.length +
      i.sources.length ===
      0;
  const roleEmpty =
    r.key_requirements.length +
      r.resume_alignment.length +
      r.potential_gaps.length +
      r.sources.length ===
    0;
  const talkingEmpty =
    t.talking_points.length +
      t.suggested_questions.length +
      t.stories_to_prepare.length ===
    0;

  return (
    <>
      <WarningsBox warnings={content.warnings ?? []} />

      <Section title="Company Overview" empty={companyEmpty}>
        <Text text={c.summary} />
        <List title="Recent news" items={c.recent_news} />
        <List title="Tech stack" items={c.tech_stack} />
        <Text title="Culture" text={c.culture_notes} />
        <Sources urls={c.sources} />
      </Section>

      <Section
        title="Interviewer Profile"
        empty={interviewerEmpty}
        emptyText={
          hasInterviewer
            ? "No information available."
            : "No interviewer provided."
        }
      >
        <Text text={i.summary} />
        <Text title="Background" text={i.background} />
        <List title="Shared interests" items={i.shared_interests} flagUnsourced />
        <List
          title="Conversation starters"
          items={i.conversation_starters}
          flagUnsourced
        />
        <Sources urls={i.sources} />
      </Section>

      <Section title="Role Insights" empty={roleEmpty}>
        <List
          title="Key requirements"
          items={r.key_requirements}
          flagUnsourced
          jobDescriptionNote={fromJobDescription(r.key_requirements)}
        />
        <List title="Resume alignment" items={r.resume_alignment} flagUnsourced />
        <List title="Potential gaps" items={r.potential_gaps} flagUnsourced />
        <Sources urls={r.sources} />
      </Section>

      <Section title="Talking Points" empty={talkingEmpty}>
        <List title="Talking points" items={t.talking_points} flagUnsourced />
        <List
          title="Suggested questions"
          items={t.suggested_questions}
          flagUnsourced
        />
        <List
          title="Stories to prepare"
          items={t.stories_to_prepare}
          flagUnsourced
        />
      </Section>
    </>
  );
}
