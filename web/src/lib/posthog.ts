import posthog from "posthog-js";

export function initPostHog() {
  if (typeof window === "undefined") return;
  if (posthog.__loaded) return;

  posthog.init("phc_NPhbB68CFkI7dXVAacRN60tnc4ADmH5dWnOVZBEkwS1", {
    api_host: "/ingest",
    ui_host: "https://eu.posthog.com",
    capture_pageview: "history_change",
    capture_pageleave: true,
    persistence: "localStorage+cookie",
    autocapture: true,
    session_recording: {
      maskAllInputs: true,
    },
  });
}
