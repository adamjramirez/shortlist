// Types matching API response schemas

export interface AuthResponse {
  token: string;
  email: string;
  user_id: number;
}

export interface User {
  id: number;
  email: string;
}

export interface Profile {
  fit_context: string;
  tracks: Record<string, unknown>;
  filters: Record<string, unknown>;
  preferences: Record<string, unknown>;
  llm: LlmConfig;
  brief: Record<string, unknown>;
  substack_sid?: string;
}

export interface LlmConfig {
  model?: string;
  api_key?: string; // only on write
  has_api_key?: boolean; // only on read
  [key: string]: unknown;
}

export interface Resume {
  id: number;
  filename: string;
  track: string | null;
  uploaded_at: string;
}

export interface JobSummary {
  id: number;
  title: string;
  company: string;
  location: string | null;
  fit_score: number | null;
  matched_track: string | null;
  salary_estimate: string | null;
  url: string | null;
  status: string | null;
  user_status: string | null;
  sources_seen: string[];
  first_seen: string | null;
  has_tailored_resume: boolean;
  company_intel: string | null;
}

export interface JobDetail extends JobSummary {
  description: string | null;
  score_reasoning: string | null;
  yellow_flags: string | null;
  enrichment: Record<string, unknown> | null;
  notes: string | null;
}

export interface JobListResponse {
  jobs: JobSummary[];
  total: number;
  page: number;
  per_page: number;
}

export interface Run {
  id: number;
  status: string;
  progress: Record<string, unknown>;
  error: string | null;
  machine_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}
