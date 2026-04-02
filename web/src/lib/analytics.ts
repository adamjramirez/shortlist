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

  coverLetterFailed: (jobId: number, company: string, error: string) =>
    trackEvent("cover_letter_failed", { job_id: jobId, company, error }),

  coverLetterCopied: (jobId: number, company: string) =>
    trackEvent("cover_letter_copied", { job_id: jobId, company }),

  coverLetterModelChanged: (model: string) =>
    trackEvent("cover_letter_model_changed", { model }),

  resumeTailored: (jobId: number, company: string) =>
    trackEvent("resume_tailored", { job_id: jobId, company }),

  resumeTailorFailed: (jobId: number, company: string, error: string) =>
    trackEvent("resume_tailor_failed", { job_id: jobId, company, error }),

  resumeDownloaded: (jobId: number, company: string) =>
    trackEvent("resume_downloaded", { job_id: jobId, company }),

  // --- Run events ---
  runStarted: () => {
    trackEvent("run_started");
    try { posthog.setPersonProperties({ has_run: true }); } catch { /* SSR */ }
  },

  runCompleted: (matches: number, duration?: number) => {
    trackEvent("run_completed", { matches, duration_seconds: duration });
    try { posthog.setPersonProperties({ has_completed_run: true }); } catch { /* SSR */ }
  },

  runCancelled: () =>
    trackEvent("run_cancelled"),

  runFailed: (error: string) =>
    trackEvent("run_failed", { error }),

  // --- Profile events ---
  profileAnalyzed: (resumeId: number) =>
    trackEvent("profile_analyzed", { resume_id: resumeId }),

  profileAnalysisFailed: (error: string) =>
    trackEvent("profile_analysis_failed", { error }),

  profileSaved: () => {
    trackEvent("profile_saved");
    try { posthog.setPersonProperties({ profile_complete: true }); } catch { /* SSR */ }
  },

  profileSaveFailed: (error: string) =>
    trackEvent("profile_save_failed", { error }),

  resumeUploaded: (filename: string) => {
    trackEvent("resume_uploaded", { filename });
    try { posthog.setPersonProperties({ has_resume: true }); } catch { /* SSR */ }
  },

  resumeUploadFailed: (filename: string, error: string) =>
    trackEvent("resume_upload_failed", { filename, error }),

  apiKeySaved: (provider: string) => {
    trackEvent("api_key_saved", { provider });
    try { posthog.setPersonProperties({ has_api_key: true, api_provider: provider }); } catch { /* SSR */ }
  },

  // --- Auth events ---
  signedUp: () =>
    trackEvent("signed_up"),

  signupFailed: (error: string) =>
    trackEvent("signup_failed", { error }),

  loggedIn: () =>
    trackEvent("logged_in"),

  loginFailed: (error: string) =>
    trackEvent("login_failed", { error }),

  // --- Filter events ---
  filterChanged: (filter: string, value: string | number | undefined) =>
    trackEvent("filter_changed", { filter, value }),

  // --- Onboarding ---
  onboardingStepViewed: (step: string) =>
    trackEvent("onboarding_step_viewed", { step }),
};
