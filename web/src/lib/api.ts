/**
 * API client — thin fetch wrapper with auth headers.
 *
 * All methods throw on non-OK responses.
 * Token stored in localStorage (client-side only).
 */

const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Don't set Content-Type for FormData (browser sets boundary)
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new ApiError(resp.status, body.detail || resp.statusText);
  }

  if (resp.status === 204) return undefined as T;
  return resp.json();
}

// --- Auth ---

import type {
  AuthResponse,
  User,
  Profile,
  Resume,
  JobListResponse,
  JobDetail,
  Run,
} from "./types";

export const auth = {
  signup: (email: string, password: string) =>
    request<AuthResponse>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<User>("/auth/me"),
};

// --- Profile ---

export const profile = {
  get: () => request<Profile>("/profile"),

  update: (data: Partial<Profile>) =>
    request<Profile>("/profile", {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  generate: (resumeId: number) =>
    request<{ fit_context: string; tracks: Record<string, unknown>; filters: Record<string, unknown> }>(
      "/profile/generate",
      { method: "POST", body: JSON.stringify({ resume_id: resumeId }) },
    ),
};

// --- Resumes ---

export const resumes = {
  list: () => request<Resume[]>("/resumes"),

  upload: (file: File, track?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (track) form.append("track", track);
    return request<Resume>("/resumes", { method: "POST", body: form });
  },

  delete: (id: number) =>
    request<void>(`/resumes/${id}`, { method: "DELETE" }),
};

// --- Jobs ---

export const jobs = {
  list: (params?: {
    min_score?: number;
    track?: string;
    user_status?: string;
    page?: number;
    per_page?: number;
  }) => {
    const search = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined) search.set(k, String(v));
      });
    }
    const qs = search.toString();
    return request<JobListResponse>(`/jobs${qs ? `?${qs}` : ""}`);
  },

  get: (id: number) => request<JobDetail>(`/jobs/${id}`),

  updateStatus: (id: number, status: string) =>
    request<JobDetail>(`/jobs/${id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),
};

// --- Runs ---

export const runs = {
  create: () => request<Run>("/runs", { method: "POST" }),

  list: () => request<Run[]>("/runs"),

  get: (id: number) => request<Run>(`/runs/${id}`),
};
