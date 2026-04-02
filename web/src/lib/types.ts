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
  providers_with_keys?: string[]; // which providers have stored keys
  provider_keys?: Record<string, string>; // only on write
  [key: string]: unknown;
}

export interface Resume {
  id: number;
  filename: string;
  track: string | null;
  resume_type: string;
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
  has_tailored_pdf: boolean;
  is_new: boolean;
  company_intel: string | null;
  score_reasoning: string | null;
}

export interface JobDetail extends JobSummary {
  description: string | null;
  yellow_flags: string | null;
  enrichment: Record<string, unknown> | null;
  interest_note: string | null;
  career_page_url: string | null;
  cover_letter: string | null;
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
