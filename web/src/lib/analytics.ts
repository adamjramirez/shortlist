/**
 * PostHog custom event tracking.
 *
 * Thin wrapper so components don't import posthog directly.
 * All event names prefixed for easy filtering in PostHog dashboard.
 */
import posthog from "posthog-js";

export function trackEvent(name: string, properties?: Record<string, unknown>) {
  try {
    posthog.capture(name, properties);
  } catch {
    // PostHog not initialized (SSR, tests) — ignore silently
  }
}

// --- Job events ---
export const track = {
  jobExpanded: (jobId: number, score: number | null, company: string) =>
    trackEvent("job_expanded", { job_id: jobId, score, company }),

  jobStatusChanged: (jobId: number, status: string, company: string) =>
    trackEvent("job_status_changed", { job_id: jobId, status, company }),

  coverLetterGenerated: (jobId: number, model: string, company: string, regenerate: boolean) =>
    trackEvent("cover_letter_generated", { job_id: jobId, model, company, regenerate }),

  resumeTailored: (jobId: number, company: string) =>
    trackEvent("resume_tailored", { job_id: jobId, company }),

  resumeDownloaded: (jobId: number, company: string) =>
    trackEvent("resume_downloaded", { job_id: jobId, company }),

  // --- Run events ---
  runStarted: () =>
    trackEvent("run_started"),

  runCompleted: (matches: number, duration?: number) =>
    trackEvent("run_completed", { matches, duration_seconds: duration }),

  runCancelled: () =>
    trackEvent("run_cancelled"),

  // --- Profile events ---
  profileAnalyzed: (resumeId: number) =>
    trackEvent("profile_analyzed", { resume_id: resumeId }),

  profileSaved: () =>
    trackEvent("profile_saved"),

  resumeUploaded: (filename: string) =>
    trackEvent("resume_uploaded", { filename }),

  // --- Auth events ---
  signedUp: () =>
    trackEvent("signed_up"),

  loggedIn: () =>
    trackEvent("logged_in"),
};
