// Mirrors backend/models/briefing.py.
export type BriefingStatus = "pending" | "running" | "complete" | "failed";

export interface CompanyOverview {
  summary: string;
  recent_news: string[];
  tech_stack: string[];
  culture_notes: string;
  sources: string[];
}

export interface InterviewerProfile {
  summary: string;
  background: string;
  shared_interests: string[];
  conversation_starters: string[];
  sources: string[];
}

export interface RoleInsights {
  key_requirements: string[];
  resume_alignment: string[];
  potential_gaps: string[];
  sources: string[];
}

export interface TalkingPoints {
  talking_points: string[];
  suggested_questions: string[];
  stories_to_prepare: string[];
}

export interface BriefingContent {
  company_overview: CompanyOverview;
  interviewer_profile: InterviewerProfile;
  role_insights: RoleInsights;
  talking_points: TalkingPoints;
  warnings: string[];
}

export interface Briefing {
  id: string;
  company: string;
  interviewer: string | null;
  role: string | null;
  interview_date: string | null;
  status: BriefingStatus;
  content: BriefingContent | null;
  created_at: string;
}

export const POLL_INTERVAL_MS = 3000;
export const POLL_MAX_MS = 5 * 60 * 1000;
export const POLL_MAX_FAILURES = 3;

// 404: unknown id. 422: id rejected by request validation (defence in depth
// if the backend ever validates the path param). Both mean "no such briefing".
export function isNotFoundStatus(status: number): boolean {
  return status === 404 || status === 422;
}
