// Pure helpers for the new-briefing form (kept out of the page so they are testable).

// Mirrors BriefingCreate.job_description max_length in backend/models/briefing.py.
export const JD_MAX_CHARS = 12000;

export type BriefingFormData = {
  company: string;
  interviewer: string;
  role: string;
  interview_date: string;
  resume_text: string;
  job_description: string;
};

export type BriefingPayload = {
  company: string;
  interviewer?: string;
  role?: string;
  interview_date?: string;
  resume_text?: string;
  job_description?: string;
};

export function buildPayload(form: BriefingFormData): BriefingPayload {
  const payload: BriefingPayload = { company: form.company.trim() };
  if (form.interviewer.trim()) payload.interviewer = form.interviewer.trim();
  if (form.role.trim()) payload.role = form.role.trim();
  if (form.interview_date) payload.interview_date = form.interview_date;
  if (form.resume_text.trim()) payload.resume_text = form.resume_text.trim();
  // Optional: the key is omitted entirely when empty.
  if (form.job_description.trim()) {
    payload.job_description = form.job_description.trim();
  }
  return payload;
}

export type JobDescriptionStatus = {
  count: number;
  over: boolean;
  message: string;
};

// Counts what will be sent (trimmed) in characters, like the server (not UTF-16
// units). The textarea has no maxLength on purpose: that would silently truncate
// a pasted posting, dropping requirements from the end without the user knowing.
export function jobDescriptionStatus(text: string): JobDescriptionStatus {
  const count = Array.from(text.trim()).length;
  const over = count > JD_MAX_CHARS;
  const fmt = (n: number) => n.toLocaleString("en-US");
  return {
    count,
    over,
    message: over
      ? `Too long by ${fmt(count - JD_MAX_CHARS)} characters. The limit is ${fmt(
          JD_MAX_CHARS
        )}; shorten it to submit.`
      : `${fmt(count)} / ${fmt(JD_MAX_CHARS)}`,
  };
}

// FastAPI 422 bodies carry `detail` as a list of objects; show something readable.
export function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown[]; msg?: unknown };
    const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
    const msg = typeof first.msg === "string" ? first.msg : "";
    if (field && msg) return `${field.replace(/_/g, " ")}: ${msg}`;
  }
  return fallback;
}
